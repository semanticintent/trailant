"""trailant CLI — see docs/technical-overview.md for the full design.

Kept as plain argparse (no third-party CLI framework) to keep the dependency
footprint small for a personal-scale open source tool. Split into one
_cmd_* function per subcommand so each is easy to read, test, and extend.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import jsonl_store
from .config import enabled_sources, load_config, trailant_home
from .indexer import reindex, load_trails, trails_path
from .models import Mark
from .utils import (
    activity_epoch,
    best_effort_activity_date,
    human_size,
    iso_week,
    recent_iso_weeks,
    today_str,
)


def marks_path():
    return trailant_home() / "marks.jsonl"


def _ensure_utf8_streams() -> None:
    """Best-effort: make stdout/stderr able to encode UTF-8 (the 🐜 mascot,
    the ⚠ in `cadence`) even where the default console encoding can't —
    legacy Windows PowerShell 5.1 / certain codepages. Guarded so a
    redirected/piped/captured/non-reconfigurable stream never turns this
    into a crash of its own."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding == "utf8":
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _cmd_reindex(args) -> None:
    config = load_config()
    result = reindex(config)
    print(
        f"scanned {result.scanned} files — "
        f"{result.updated} updated, {result.unchanged} unchanged, {result.skipped} skipped"
    )
    for source_name, cov in result.by_source.items():
        note = "  ⚠ found nothing — check the source path/adapter" if cov.scanned == 0 else ""
        print(f"  {source_name}: {cov.scanned} files — "
              f"{cov.updated} updated, {cov.unchanged} unchanged, {cov.skipped} skipped{note}")
    print(f"trails: {trails_path()}")


def _cmd_resume(args) -> None:
    trails = load_trails()
    if not trails:
        print("No sessions indexed yet. Run `trailant reindex` first.")
        return
    trails.sort(key=activity_epoch, reverse=True)
    limit = args.limit or 15
    shown = trails[:limit]

    if args.html or args.output:
        from .html_report import render_resume_html
        output_path = Path(args.output) if args.output else Path("trailant-resume.html")
        output_path.write_text(render_resume_html(shown), encoding="utf-8")
        print(f"Wrote HTML report to {output_path}")
        return

    for s in shown:
        title = s.get("ai_title") or "(untitled)"
        print(f"[{s['source']:11}] {s.get('started_at') or '?':20}  {title}")
        print(f"              project: {s.get('project')}")
        print(f"              session: {s['session_id']}  "
              f"prompts={s.get('prompt_count', 0)}  size={human_size(s.get('size_bytes', 0))}")
        print()


def _cmd_status(args) -> None:
    trails = load_trails()
    marks = jsonl_store.read_all(marks_path())

    if trails:
        latest = max(trails, key=activity_epoch)
        print(f"Last session: [{latest['source']}] {latest.get('ai_title') or '(untitled)'}")
        print(f"  project: {latest.get('project')}")
        print(f"  started: {latest.get('started_at')}")
        print(f"  last activity: {latest.get('ended_at') or '?'}")
    else:
        print("No sessions indexed yet. Run `trailant reindex`.")

    if marks:
        latest_mark = marks[-1]
        print(f"\nLast mark ({latest_mark['kind']}, {latest_mark['date']}):")
        print(f"  {latest_mark['content'][:120]}")
    else:
        print("\nNo marks logged yet. Try `trailant log \"...\"`.")

    coverage = _index_coverage_line(trails)
    if coverage:
        print(f"\n{coverage}")


def _index_coverage_line(trails: list[dict]) -> str | None:
    """One line answering "can I trust this report" — when the index was
    last refreshed, and per-source counts. A configured source sitting at
    0 sessions is flagged explicitly rather than just quietly absent —
    that distinction (unknown/broken vs genuinely zero activity) is what
    would have made the Codex adapter losing track of current sessions
    visible immediately instead of requiring a full manual investigation."""
    path = trails_path()
    if not path.exists():
        return None
    try:
        refreshed = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None

    counts = Counter(s.get("source", "unknown") for s in trails)
    config = load_config()
    parts = []
    for source_name in enabled_sources(config):
        n = counts.get(source_name, 0)
        flag = " ⚠ zero sessions — check source path/adapter" if n == 0 else ""
        parts.append(f"{source_name}: {n} sessions{flag}")
    sources_note = ", ".join(parts) if parts else "no sources configured"
    return f"Index: refreshed {refreshed.strftime('%Y-%m-%d %H:%M')} — {sources_note}"


def _cmd_log(args) -> None:
    mark = Mark(date=today_str(), kind="self_log", content=args.note)
    jsonl_store.append(marks_path(), mark.to_dict())
    print(f"Logged: {mark.content}")


def _cmd_close(args) -> None:
    trails = load_trails()
    session = None
    if args.session_id:
        session = next((s for s in trails if s["session_id"] == args.session_id), None)
        if session is None:
            print(f"No session found with id {args.session_id}. Run `trailant resume` to list.",
                  file=sys.stderr)
            sys.exit(1)
    else:
        if not trails:
            print("No sessions indexed yet.", file=sys.stderr)
            sys.exit(1)
        session = max(trails, key=activity_epoch)

    draft = (
        f"Closed session on: {session.get('ai_title') or '(untitled)'}\n"
        f"Project: {session.get('project')}\n"
        f"Prompts: {session.get('prompt_count', 0)}  Source: {session.get('source')}"
    )

    print("--- draft (not sent — review before confirming) ---")
    print(draft)
    print("-----------------------------------------------------")

    config = load_config()
    if config.get("self_log", {}).get("hold_before_send", True):
        confirm = input("Save this as a mark? [y/N] ").strip().lower()
        if confirm != "y":
            print("Discarded.")
            return

    mark = Mark(
        date=today_str(),
        kind="session_close",
        content=draft,
        session_id=session["session_id"],
    )
    jsonl_store.append(marks_path(), mark.to_dict())
    print("Saved to marks.jsonl. (Sending to email/etc is not wired up in this starter scaffold —"
          " see self_log.send_via in config.example.yaml.)")


def _cmd_today(args, *, now: datetime | None = None) -> None:
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    trails = [s for s in load_trails() if best_effort_activity_date(s) == today]
    marks = [m for m in jsonl_store.read_all(marks_path()) if m.get("date") == today]

    print(f"=== {today} ===")
    if not trails and not marks:
        print("Nothing recorded yet today. (This might be a gap day — consider `trailant log`.)")
        return

    if trails:
        print(f"\nSessions ({len(trails)}):")
        for s in trails:
            print(f"  [{s['source']}] {s.get('ai_title') or '(untitled)'}  "
                  f"({s.get('prompt_count', 0)} prompts)")

    if marks:
        print(f"\nMarks ({len(marks)}):")
        for m in marks:
            print(f"  ({m['kind']}) {m['content'][:100]}")


def _cmd_week(args, *, now: datetime | None = None) -> None:
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    start = now - timedelta(days=now.weekday())  # Monday
    days = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    trails_by_day: dict[str, list[dict]] = defaultdict(list)
    for s in load_trails():
        d = best_effort_activity_date(s)
        if d in days:
            trails_by_day[d].append(s)

    marks_by_day: dict[str, list[dict]] = defaultdict(list)
    for m in jsonl_store.read_all(marks_path()):
        if m.get("date") in days:
            marks_by_day[m["date"]].append(m)

    print(f"=== Week of {days[0]} ===")
    for d in days:
        sessions = trails_by_day.get(d, [])
        marks = marks_by_day.get(d, [])
        # Fixed-width zero-padded ISO dates sort lexicographically the same
        # as chronologically, so a plain string compare is safe here.
        gap = " (gap day — no activity found)" if (not sessions and not marks and d <= today) else ""
        print(f"\n{d}{gap}")
        for s in sessions:
            print(f"  [{s['source']}] {s.get('ai_title') or '(untitled)'}")
        for m in marks:
            print(f"  ({m['kind']}) {m['content'][:100]}")


def _cmd_cadence(args, *, now: datetime | None = None) -> None:
    config = load_config()
    baseline_weeks = config.get("cadence", {}).get("baseline_window_weeks", 12)
    valley_flag_after = config.get("cadence", {}).get("valley_flag_after_weeks", 8)

    trails = load_trails()
    if not trails:
        print("No data yet — run `trailant reindex` first.")
        return

    counts: Counter[str] = Counter()
    for s in trails:
        wk = iso_week(best_effort_activity_date(s))
        if wk:
            counts[wk] += 1

    weeks_sorted = recent_iso_weeks(baseline_weeks, today=now)
    values = [counts[w] for w in weeks_sorted]
    avg = sum(values) / len(values) if values else 0

    # crude valley detection: weeks meaningfully below average, most recent one
    valley_weeks = [w for w in weeks_sorted if counts[w] < avg * 0.5]
    valley_note = None
    if valley_weeks:
        last_valley = valley_weeks[-1]
        weeks_since = len(weeks_sorted) - weeks_sorted.index(last_valley) - 1
        if weeks_since >= valley_flag_after:
            valley_note = (f"⚠ {weeks_since} weeks since your last low-activity week ({last_valley}). "
                            f"Historically this is when a valley week has been due — worth considering one.")

    if args.html or args.output:
        from .html_report import render_cadence_html
        output_path = Path(args.output) if args.output else Path("trailant-cadence.html")
        output_path.write_text(render_cadence_html(weeks_sorted, counts, avg, valley_note), encoding="utf-8")
        print(f"Wrote HTML report to {output_path}")
        return

    print(f"Session count by week (last {len(weeks_sorted)} weeks):")
    for w in weeks_sorted:
        bar = "#" * counts[w]
        print(f"  {w}: {counts[w]:3d}  {bar}")
    print(f"\nAverage: {avg:.1f} sessions/week")

    if valley_note:
        print(f"\n{valley_note}")
    elif not valley_weeks:
        print(f"\nNo clear valley week detected yet in this window.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trailant", description="Follow your own trail. 🐜")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("reindex", help="Rebuild the trail index from all configured sources.")
    p.set_defaults(func=_cmd_reindex)

    p = sub.add_parser("resume", help="List recent sessions across all vendors.")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--html", action="store_true",
                    help="Write a static HTML report instead of printing to the terminal.")
    p.add_argument("--output", default=None,
                    help="Path for the HTML report (default: ./trailant-resume.html). Implies --html.")
    p.set_defaults(func=_cmd_resume)

    p = sub.add_parser("status", help="Quick 'where was I' summary.")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("log", help="Add a manual self-log entry.")
    p.add_argument("note")
    p.set_defaults(func=_cmd_log)

    p = sub.add_parser("close", help="Draft a session-close mark (optionally for a specific session id).")
    p.add_argument("session_id", nargs="?", default=None)
    p.set_defaults(func=_cmd_close)

    p = sub.add_parser("today", help="Reconstructed view of today's activity.")
    p.set_defaults(func=_cmd_today)

    p = sub.add_parser("week", help="Timesheet-shaped rollup for the current week.")
    p.set_defaults(func=_cmd_week)

    p = sub.add_parser("cadence", help="Velocity trend vs. your own baseline.")
    p.add_argument("--html", action="store_true",
                    help="Write a static HTML report instead of printing to the terminal.")
    p.add_argument("--output", default=None,
                    help="Path for the HTML report (default: ./trailant-cadence.html). Implies --html.")
    p.set_defaults(func=_cmd_cadence)

    return parser


def main(argv: list[str] | None = None) -> None:
    _ensure_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
