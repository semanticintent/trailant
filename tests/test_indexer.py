import os
from pathlib import Path

import pytest

from trailant import jsonl_store
from trailant.indexer import reindex, trails_path


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAILANT_HOME", str(tmp_path / ".trailant"))
    return tmp_path


def _config(claude_root: Path, codex_root: Path) -> dict:
    return {
        "sources": {
            "claude_code": {"enabled": True, "root": str(claude_root)},
            "codex": {"enabled": True, "root": str(codex_root)},
        }
    }


def test_reindex_finds_fixture_sessions(isolated_home):
    fixtures = Path(__file__).parent / "fixtures"
    config = _config(fixtures / "claude_code", fixtures / "codex_sessions")

    result = reindex(config)
    # 1 claude_code session + 2 codex rollout files (one of which is a
    # subagent session that read_metadata correctly skips).
    assert result.scanned == 3
    assert result.updated == 2
    assert result.skipped == 1
    assert result.unchanged == 0

    records = jsonl_store.read_all(trails_path())
    sources = {r["source"] for r in records}
    assert sources == {"claude_code", "codex"}
    assert len(records) == 2


def test_reindex_is_idempotent_when_files_unchanged(isolated_home):
    fixtures = Path(__file__).parent / "fixtures"
    config = _config(fixtures / "claude_code", fixtures / "codex_sessions")

    reindex(config)
    second = reindex(config)

    assert second.updated == 0
    assert second.unchanged == 2
    assert second.skipped == 1
