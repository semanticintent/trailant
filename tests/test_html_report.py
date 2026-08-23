from pathlib import Path

import pytest

from trailant.cli import main
from trailant.html_report import render_cadence_html, render_resume_html
from trailant.indexer import reindex


def test_render_resume_html_includes_session_fields():
    trails = [{
        "source": "claude_code",
        "ai_title": "Fix <script> tags & other <b>edge</b> cases",
        "project": "/Users/me/code/ingest",
        "prompt_count": 3,
        "size_bytes": 1024,
    }]
    out = render_resume_html(trails)
    assert "trailant" in out
    assert "[claude_code]" in out
    assert "/Users/me/code/ingest" in out
    assert "3 prompts" in out
    # user-controlled content must be escaped, not injected as raw HTML
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_render_resume_html_handles_no_sessions():
    out = render_resume_html([])
    assert "No sessions indexed yet." in out


def test_render_cadence_html_includes_bars_and_average():
    weeks = ["2026-W32", "2026-W33"]
    counts = {"2026-W32": 3, "2026-W33": 1}
    out = render_cadence_html(weeks, counts, avg=2.0, valley_note=None)
    assert "2026-W32" in out
    assert "2026-W33" in out
    assert "Average: 2.0 sessions/week" in out
    assert "No valley currently flagged" in out


def test_render_cadence_html_includes_valley_note_when_given():
    out = render_cadence_html(["2026-W32"], {"2026-W32": 1}, avg=1.0,
                               valley_note="⚠ 8 weeks since your last low-activity week")
    assert "8 weeks since your last low-activity week" in out


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAILANT_HOME", str(tmp_path / ".trailant"))
    return tmp_path


def test_cli_resume_html_writes_file(isolated_home, monkeypatch, tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    config = {
        "sources": {
            "claude_code": {"enabled": True, "root": str(fixtures / "claude_code")},
            "codex": {"enabled": True, "root": str(fixtures / "codex_sessions")},
        }
    }
    reindex(config)

    monkeypatch.chdir(tmp_path)
    main(["resume", "--html"])

    out_file = tmp_path / "trailant-resume.html"
    assert out_file.exists()
    assert "trailant" in out_file.read_text()


def test_cli_cadence_html_respects_output_path(isolated_home, monkeypatch, tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    config = {
        "sources": {
            "claude_code": {"enabled": True, "root": str(fixtures / "claude_code")},
            "codex": {"enabled": True, "root": str(fixtures / "codex_sessions")},
        }
    }
    reindex(config)

    monkeypatch.chdir(tmp_path)
    custom_path = tmp_path / "custom-cadence.html"
    main(["cadence", "--output", str(custom_path)])

    assert custom_path.exists()
    assert "cadence" in custom_path.read_text()
