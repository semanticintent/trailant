import io
import sys

import pytest

from trailant import cli


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
