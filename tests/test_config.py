import pytest

from trailant.config import config_path, enabled_sources, load_config


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAILANT_HOME", str(tmp_path / ".trailant"))
    return tmp_path


def test_partial_config_edit_keeps_sibling_defaults(isolated_home):
    """A user editing config.yaml to change one nested field (e.g. disabling
    codex) should not silently drop unrelated defaults like claude_code."""
    load_config()  # bootstraps the default config.yaml on disk
    config_path().write_text("sources:\n  codex:\n    enabled: false\n", encoding="utf-8")

    config = load_config()

    assert config["sources"]["codex"]["enabled"] is False
    assert config["sources"]["claude_code"]["enabled"] is True
    assert config["sources"]["claude_code"]["root"] == "~/.claude/projects"
    assert set(enabled_sources(config)) == {"claude_code"}
