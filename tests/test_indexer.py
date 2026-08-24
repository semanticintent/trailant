import os
from pathlib import Path

import pytest

from trailant import jsonl_store
from trailant.indexer import INDEX_SCHEMA_VERSION, reindex, trails_path


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAILANT_HOME", str(tmp_path / ".trailant"))
    # reindex() exercises CodexAdapter.read_metadata(), which now consults a
    # SQLite session index under $CODEX_HOME — without isolating it here,
    # tests would silently query the real ~/.codex on whatever machine
    # runs them (present on this very machine).
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty_codex_home"))
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
    # 6 claude_code sessions + 3 codex rollout files (one of which is a
    # subagent session that read_metadata correctly skips).
    assert result.scanned == 9
    assert result.updated == 8
    assert result.skipped == 1
    assert result.unchanged == 0

    records = jsonl_store.read_all(trails_path())
    sources = {r["source"] for r in records}
    assert sources == {"claude_code", "codex"}
    assert len(records) == 8

    assert result.by_source["claude_code"].scanned == 6
    assert result.by_source["claude_code"].updated == 6
    assert result.by_source["claude_code"].skipped == 0
    assert result.by_source["codex"].scanned == 3
    assert result.by_source["codex"].updated == 2
    assert result.by_source["codex"].skipped == 1


def test_reindex_reports_zero_coverage_for_a_source_that_finds_nothing(isolated_home, tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    empty_codex_root = tmp_path / "no-codex-here"
    config = _config(fixtures / "claude_code", empty_codex_root)

    result = reindex(config)

    # A configured source with a root that finds nothing still shows up in
    # by_source with zero counts, rather than being silently absent — this
    # is what makes an adapter going blind visible at all.
    assert "codex" in result.by_source
    assert result.by_source["codex"].scanned == 0
    assert result.by_source["codex"].updated == 0


def test_reindex_is_idempotent_when_files_unchanged(isolated_home):
    fixtures = Path(__file__).parent / "fixtures"
    config = _config(fixtures / "claude_code", fixtures / "codex_sessions")

    reindex(config)
    second = reindex(config)

    assert second.updated == 0
    assert second.unchanged == 8
    assert second.skipped == 1


def test_reindex_reparses_when_schema_version_is_stale(isolated_home):
    fixtures = Path(__file__).parent / "fixtures"
    config = _config(fixtures / "claude_code", fixtures / "codex_sessions")

    reindex(config)
    records = jsonl_store.read_all(trails_path())
    for r in records:
        assert r["_index_schema_version"] == INDEX_SCHEMA_VERSION
        del r["_index_schema_version"]  # simulate an index written before this field existed
    jsonl_store.write_all(trails_path(), records)

    second = reindex(config)

    assert second.updated == 8
    assert second.unchanged == 0
    assert second.skipped == 1


def test_reindex_respects_secrets_disabled_config(isolated_home):
    fixtures = Path(__file__).parent / "fixtures"
    config = _config(fixtures / "claude_code", fixtures / "codex_sessions")
    config["secrets"] = {"enabled": False}

    reindex(config)
    records = jsonl_store.read_all(trails_path())

    secret_record = next(r for r in records if r["session_id"] == "f6a7b8c9-1111-2222-3333-444455556666")
    assert secret_record["secret_hits"] == 0
    assert "password" in secret_record["ai_title"]  # not redacted when scanning is off
