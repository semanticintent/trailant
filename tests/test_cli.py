import argparse
import io
import sys
from datetime import datetime

import pytest

from trailant import cli, jsonl_store
from trailant.indexer import trails_path
from trailant.utils import activity_epoch, recent_iso_weeks


def _cp1252_stdout() -> io.TextIOWrapper:
    # Recreates the real Windows PowerShell 5.1 / Git Bash failure: a
    # TextIOWrapper that can't encode U+1F41C (the 🐜 mascot), strict
    # errors. pytest's own capsys already normalizes to UTF-8, which is why
    # CI (even windows-latest, which runs pwsh for `run:` steps by default)
    # never reproduced this bug.
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")


def test_cp1252_stream_reproduces_the_bug_without_the_fix():
    stream = _cp1252_stdout()
    with pytest.raises(UnicodeEncodeError):
        stream.write("🐜")


def test_ensure_utf8_streams_fixes_non_utf8_stdout(monkeypatch):
    stream = _cp1252_stdout()
    monkeypatch.setattr(sys, "stdout", stream)
    cli._ensure_utf8_streams()
    stream.write("🐜")  # must not raise post-fix
    stream.flush()
    assert "🐜".encode("utf-8") in stream.buffer.getvalue()


def test_main_help_survives_non_utf8_stdout(monkeypatch):
    stream = _cp1252_stdout()
    monkeypatch.setattr(sys, "stdout", stream)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    stream.flush()
    assert b"trail" in stream.buffer.getvalue()


class _NoReconfigureStream:
    encoding = "ascii"

    def write(self, s):
        pass


def test_ensure_utf8_streams_skips_stream_without_reconfigure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _NoReconfigureStream())
    monkeypatch.setattr(sys, "stderr", _NoReconfigureStream())
    cli._ensure_utf8_streams()  # must not raise


# --- Phase 2: reporting honesty (activity-based, not session-start-based) ---


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAILANT_HOME", str(tmp_path / ".trailant"))
    return tmp_path


def _trail_record(session_id, *, source="claude_code", project="/x",
                   started_at=None, ended_at=None, file_mtime=0.0,
                   ai_title="untitled", prompt_count=1, size_bytes=100):
    return {
        "session_id": session_id,
        "source": source,
        "project": project,
        "started_at": started_at,
        "ended_at": ended_at,
        "prompt_count": prompt_count,
        "size_bytes": size_bytes,
        "file_path": f"/fake/{session_id}.jsonl",
        "file_mtime": file_mtime,
        "ai_title": ai_title,
    }


def test_status_picks_by_activity_not_started_at(isolated_home, capsys):
    old_start_recent_activity = _trail_record(
        "s1", started_at="2026-08-01T09:00:00Z", ended_at="2026-08-24T10:00:00Z",
        ai_title="Old start, active today")
    recent_start_stale = _trail_record(
        "s2", started_at="2026-08-23T09:00:00Z", ended_at="2026-08-23T09:30:00Z",
        ai_title="Recent start, stale")
    jsonl_store.write_all(trails_path(), [old_start_recent_activity, recent_start_stale])

    cli._cmd_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert "Old start, active today" in out
    assert "Recent start, stale" not in out


def test_resume_sorts_by_activity_not_started_at(isolated_home, capsys):
    should_be_first = _trail_record(
        "s1", started_at="2026-08-01T09:00:00Z", ended_at="2026-08-24T10:00:00Z",
        ai_title="Should be first")
    should_be_second = _trail_record(
        "s2", started_at="2026-08-23T09:00:00Z", ended_at="2026-08-23T09:30:00Z",
        ai_title="Should be second")
    # Written deliberately out of activity order.
    jsonl_store.write_all(trails_path(), [should_be_second, should_be_first])

    cli._cmd_resume(argparse.Namespace(limit=None, html=False, output=None, print_command=False))
    out = capsys.readouterr().out

    assert out.index("Should be first") < out.index("Should be second")


def test_close_default_picks_by_activity_not_started_at(isolated_home, capsys, monkeypatch):
    should_be_closed = _trail_record(
        "s1", started_at="2026-08-01T09:00:00Z", ended_at="2026-08-24T10:00:00Z",
        ai_title="Should be closed")
    not_this_one = _trail_record(
        "s2", started_at="2026-08-23T09:00:00Z", ended_at="2026-08-23T09:30:00Z",
        ai_title="Not this one")
    jsonl_store.write_all(trails_path(), [should_be_closed, not_this_one])
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

    cli._cmd_close(argparse.Namespace(session_id=None))
    out = capsys.readouterr().out

    assert "Should be closed" in out
    assert "Not this one" not in out


def test_today_includes_resumed_old_session(isolated_home, capsys):
    now = datetime(2026, 8, 24, 15, 0, 0)
    record = _trail_record(
        "s1", started_at="2026-08-21T09:00:00Z", ended_at="2026-08-24T14:00:00Z",
        ai_title="Resumed today")
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_today(argparse.Namespace(), now=now)
    out = capsys.readouterr().out

    assert "Resumed today" in out


def test_week_does_not_flag_future_days_as_gaps(isolated_home, capsys):
    now = datetime(2026, 8, 24, 12, 0, 0)  # a Monday, per the validation report

    cli._cmd_week(argparse.Namespace(), now=now)
    out = capsys.readouterr().out

    # Today, with no activity yet, is still a legitimate gap.
    assert "2026-08-24 (gap day" in out
    # But the rest of this week hasn't happened yet — no gap claim for it.
    for future_day in ("2026-08-25", "2026-08-26", "2026-08-27",
                        "2026-08-28", "2026-08-29", "2026-08-30"):
        assert f"{future_day} (gap day" not in out


def test_cadence_zero_fills_contiguous_weeks_and_counts_current_week(isolated_home, capsys):
    now = datetime(2026, 8, 24, 12, 0, 0)
    record = _trail_record(
        "s1", started_at="2026-07-01T09:00:00Z", ended_at="2026-08-24T10:00:00Z",
        ai_title="resumed this week")
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_cadence(argparse.Namespace(html=False, output=None), now=now)
    out = capsys.readouterr().out

    weeks = recent_iso_weeks(12, today=now)
    assert len(weeks) == 12
    # Contiguous + zero-filled: every week label appears, including the
    # ones with no sessions at all.
    for w in weeks:
        assert w in out
    # The session's ended_at (this week) counts it toward the *current*
    # week, not the week it started in.
    current_week = weeks[-1]
    assert f"  {current_week}: {1:3d}  #" in out


def test_activity_epoch_handles_trailing_z_suffix():
    epoch = activity_epoch({"ended_at": "2026-08-22T11:02:00Z"})
    assert epoch > 0


def test_activity_epoch_falls_back_to_file_mtime():
    epoch = activity_epoch({"ended_at": None, "file_mtime": 1755856920.0})
    assert epoch == 1755856920.0


# --- Phase 3: source coverage reporting ---


def test_status_shows_index_coverage_line(isolated_home, capsys):
    record = _trail_record("s1", source="claude_code",
                            started_at="2026-08-24T09:00:00Z", ended_at="2026-08-24T09:30:00Z")
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert "Index: refreshed" in out
    assert "claude_code: 1 sessions" in out


def test_status_flags_a_configured_source_with_zero_sessions(isolated_home, capsys):
    record = _trail_record("s1", source="claude_code",
                            started_at="2026-08-24T09:00:00Z", ended_at="2026-08-24T09:30:00Z")
    jsonl_store.write_all(trails_path(), [record])
    # Default config enables both claude_code and codex — codex has no
    # sessions in this index at all, which should be flagged, not just
    # silently omitted.

    cli._cmd_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert "codex: 0 sessions" in out
    assert "⚠" in out


def test_resume_print_command_shows_the_real_vendor_resume_command(isolated_home, capsys):
    record = _trail_record("s1", source="claude_code", project="/Users/me/code/x",
                            ai_title="Fix the thing")
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_resume(argparse.Namespace(limit=None, html=False, output=None, print_command=True))
    out = capsys.readouterr().out

    # Two separate lines, not `cd X && Y` — `&&` chaining is a parse error
    # on Windows PowerShell 5.1.
    assert "resume:  cd /Users/me/code/x" in out
    assert "claude --resume s1" in out
    assert "&&" not in out


def test_resume_without_print_command_omits_resume_line(isolated_home, capsys):
    record = _trail_record("s1", source="claude_code", project="/Users/me/code/x")
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_resume(argparse.Namespace(limit=None, html=False, output=None, print_command=False))
    out = capsys.readouterr().out

    assert "resume:" not in out


def test_resume_print_command_skips_unknown_source(isolated_home, capsys):
    record = _trail_record("s1", source="some_future_vendor", project="/x")
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_resume(argparse.Namespace(limit=None, html=False, output=None, print_command=True))
    out = capsys.readouterr().out

    assert "resume:" not in out  # no crash, no guessed command


# --- Phase 6: secret-leak detection ---


def test_resume_flags_a_session_with_secret_hits(isolated_home, capsys):
    record = _trail_record("s1", ai_title="(untitled — possible secret redacted)")
    record["secret_hits"] = 2
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_resume(argparse.Namespace(limit=None, html=False, output=None, print_command=False))
    out = capsys.readouterr().out

    assert "possible secret detected (2x)" in out


def test_status_flags_the_latest_session_with_secret_hits(isolated_home, capsys):
    record = _trail_record("s1", ai_title="(untitled — possible secret redacted)",
                            started_at="2026-08-24T09:00:00Z", ended_at="2026-08-24T09:30:00Z")
    record["secret_hits"] = 1
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert "possible secret detected (1x)" in out


def test_status_coverage_line_notes_aggregate_secret_count(isolated_home, capsys):
    clean = _trail_record("s1", ai_title="fine")
    flagged = _trail_record("s2", ai_title="(untitled — possible secret redacted)")
    flagged["secret_hits"] = 3
    jsonl_store.write_all(trails_path(), [clean, flagged])

    cli._cmd_status(argparse.Namespace())
    out = capsys.readouterr().out

    assert "1 session(s) contain probable secrets" in out


# --- Phase 4: `trailant diff` ("what changed since last run") ---


def test_diff_first_run_captures_baseline_without_claiming_a_change(isolated_home, capsys):
    record = _trail_record("s1", ai_title="First ever session")
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_diff(argparse.Namespace())
    out = capsys.readouterr().out

    assert "No previous snapshot" in out
    assert "baseline" in out
    assert cli._diff_snapshot_path().exists()


def test_diff_reports_nothing_changed_on_second_run_with_no_changes(isolated_home, capsys):
    record = _trail_record("s1", ai_title="Stable session")
    jsonl_store.write_all(trails_path(), [record])

    cli._cmd_diff(argparse.Namespace())
    capsys.readouterr()  # discard baseline output
    cli._cmd_diff(argparse.Namespace())
    out = capsys.readouterr().out

    assert "(nothing changed)" in out
    assert "new session" not in out


def test_diff_reports_new_sessions_since_last_run(isolated_home, capsys):
    old = _trail_record("s1", ai_title="Already known")
    jsonl_store.write_all(trails_path(), [old])
    cli._cmd_diff(argparse.Namespace())
    capsys.readouterr()

    new = _trail_record("s2", ai_title="Brand new session")
    jsonl_store.write_all(trails_path(), [old, new])
    cli._cmd_diff(argparse.Namespace())
    out = capsys.readouterr().out

    assert "1 new session(s)" in out
    assert "Brand new session" in out
    assert "Already known" not in out
    assert "pool size 1 -> 2" in out


def test_diff_flags_a_source_that_went_from_active_to_zero(isolated_home, capsys):
    a = _trail_record("s1", source="claude_code", ai_title="a")
    b = _trail_record("s2", source="codex", ai_title="b")
    jsonl_store.write_all(trails_path(), [a, b])
    cli._cmd_diff(argparse.Namespace())
    capsys.readouterr()

    # codex's only session vanished from the index — simulates an adapter
    # silently losing track of a source between runs.
    jsonl_store.write_all(trails_path(), [a])
    cli._cmd_diff(argparse.Namespace())
    out = capsys.readouterr().out

    assert "SOURCE DRIFTED" in out
    assert "codex" in out


def test_diff_reports_new_marks_since_last_run(isolated_home, capsys):
    record = _trail_record("s1")
    jsonl_store.write_all(trails_path(), [record])
    cli._cmd_diff(argparse.Namespace())
    capsys.readouterr()

    cli._cmd_log(argparse.Namespace(note="a new note"))
    capsys.readouterr()
    cli._cmd_diff(argparse.Namespace())
    out = capsys.readouterr().out

    assert "1 new mark(s) logged" in out


def test_diff_recovers_from_a_corrupt_snapshot_file(isolated_home, capsys):
    record = _trail_record("s1")
    jsonl_store.write_all(trails_path(), [record])
    cli._diff_snapshot_path().parent.mkdir(parents=True, exist_ok=True)
    cli._diff_snapshot_path().write_text("not valid json{{{", encoding="utf-8")

    cli._cmd_diff(argparse.Namespace())  # must not raise
    out = capsys.readouterr().out

    assert "No previous snapshot" in out
