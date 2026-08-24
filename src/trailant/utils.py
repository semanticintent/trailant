from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

# Tags AI coding tools inject as a literal "user" turn — a slash command's
# caveat banner, a hook's stdout, a plugin list — rather than something the
# human actually typed. Best-effort, not exhaustive: vendors add more of
# these over time, so a session's real opening prompt should be found by
# skipping past them, not by assuming the first "user" record is it.
SYSTEM_WRAPPER_TAGS = frozenset({
    "local-command-caveat",
    "local-command-stdout",
    "command-name",
    "command-message",
    "command-args",
    "system-reminder",
    "user-prompt-submit-hook",
    "ide_selection",
    "ide_diagnostics",
    "ide_opened_file",
    "recommended_plugins",
    "environment_context",
})

# Some wrapper content isn't an XML-style tag at all — a Codex markdown
# heading, confirmed verbatim from a real Windows session's generated HTML
# output rather than guessed.
SYSTEM_WRAPPER_PREFIXES = (
    "# AGENTS.md instructions",
)

_WRAPPER_TAG_RE = re.compile(r"^<([a-zA-Z][\w-]*)>")


def is_system_wrapper_text(text: str) -> bool:
    """True if `text` is a known system-injected wrapper rather than
    human-typed content — e.g. the <local-command-caveat> block Claude Code
    inserts after a slash command, or Codex's <environment_context> /
    AGENTS.md scaffolding."""
    if not text:
        return False
    stripped = text.strip()
    match = _WRAPPER_TAG_RE.match(stripped)
    if match and match.group(1) in SYSTEM_WRAPPER_TAGS:
        return True
    return stripped.startswith(SYSTEM_WRAPPER_PREFIXES)


def best_effort_date(session: dict) -> str:
    """Return a YYYY-MM-DD string for a trail record, preferring started_at,
    falling back to file_mtime. Sessions are noisy — timestamps aren't always
    present in every vendor's metadata line, so this never raises."""
    started = session.get("started_at")
    if started:
        try:
            return started[:10]
        except Exception:
            pass
    mtime = session.get("file_mtime")
    if mtime:
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    return "unknown"


def best_effort_activity_date(session: dict) -> str:
    """Return a YYYY-MM-DD string for when a session was last *active* —
    ended_at first (most authoritative), then file_mtime, then started_at
    as a last resort. Deliberately distinct from best_effort_date(): that
    answers "when did this start", this answers "was this touched on date
    D" — a session resumed today can have a started_at from days ago and
    would otherwise be invisible to `today`/`week`/`cadence`."""
    ended = session.get("ended_at")
    if ended:
        try:
            return ended[:10]
        except Exception:
            pass
    mtime = session.get("file_mtime")
    if mtime:
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    started = session.get("started_at")
    if started:
        try:
            return started[:10]
        except Exception:
            pass
    return "unknown"


def activity_epoch(session: dict) -> float:
    """Best available signal for 'when was this session last touched', as a
    UTC epoch float — lets sessions be ranked/sorted by recency without
    conflating ended_at's ISO8601 string and file_mtime's epoch float."""
    ended = session.get("ended_at")
    if ended:
        try:
            # Python 3.10 (this project's floor) doesn't parse a bare
            # trailing "Z" in fromisoformat — normalize it first.
            return datetime.fromisoformat(ended.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            pass
    return session.get("file_mtime") or 0.0


def recent_iso_weeks(n: int, *, today: Optional[datetime] = None) -> list[str]:
    """Last `n` ISO week labels (YYYY-Www), oldest first, ending with the
    current calendar week — contiguous regardless of whether any session
    activity fell in a given week, so a zero-activity week shows as a real
    zero instead of silently compressing the reported window."""
    ref = today or datetime.now()
    monday_this_week = ref - timedelta(days=ref.weekday())
    weeks = []
    for i in range(n - 1, -1, -1):
        monday = monday_this_week - timedelta(weeks=i)
        year, week, _ = monday.isocalendar()
        weeks.append(f"{year}-W{week:02d}")
    return weeks


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TB"


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def iso_week(date_str: str) -> Optional[str]:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"
