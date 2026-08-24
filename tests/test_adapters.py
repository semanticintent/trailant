import json
from pathlib import Path

import pytest

from trailant.adapters.claude_code import ClaudeCodeAdapter
from trailant.adapters.codex import CodexAdapter
from tests.fixtures.codex_state_builder import (
    build_state_db,
    build_state_db_missing_rollout_path_column,
    build_thread_history_db,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_codex_home(tmp_path, monkeypatch):
    """Every test in this file gets an empty, isolated $CODEX_HOME by
    default — CodexAdapter.read_metadata() now consults a SQLite session
    index, and without this, tests would silently query the real
    ~/.codex/state_*.sqlite on whatever machine runs them (present on this
    very machine). Tests that specifically want a populated state DB
    override this by setting CODEX_HOME again to a dir they populate."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty_codex_home"))


def test_claude_code_lists_session_file():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    files = adapter.list_session_files()
    names = {f.name for f in files}
    assert names == {
        "db4961c3-1111-2222-3333-444455556666.jsonl",
        "f00dcafe-1111-2222-3333-444455556666.jsonl",
        "a1b2c3d4-1111-2222-3333-444455556666.jsonl",
        "b2c3d4e5-1111-2222-3333-444455556666.jsonl",
        "c3d4e5f6-1111-2222-3333-444455556666.jsonl",
        "f6a7b8c9-1111-2222-3333-444455556666.jsonl",
    }


def test_claude_code_metadata_extraction():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    path = FIXTURES / "claude_code" / "-Users-me-code-ingest" / "db4961c3-1111-2222-3333-444455556666.jsonl"
    meta = adapter.read_metadata(path)

    assert meta is not None
    assert meta.session_id == "db4961c3-1111-2222-3333-444455556666"
    assert meta.source == "claude_code"
    assert meta.project == "/Users/me/code/ingest"
    assert meta.prompt_count == 2
    assert meta.started_at == "2026-08-22T09:14:00Z"
    assert meta.ended_at == "2026-08-22T11:02:00Z"
    # summary line should win over the truncated first-message fallback
    assert meta.ai_title == "Refactor session-resume report parser"


def test_claude_code_skips_wrapper_tag_when_picking_title():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    path = FIXTURES / "claude_code" / "-Users-me-code-billing" / "f00dcafe-1111-2222-3333-444455556666.jsonl"
    meta = adapter.read_metadata(path)

    assert meta is not None
    # No "summary" line in this fixture, and the first "user" turn is a
    # <local-command-caveat> wrapper — the title should skip past it to the
    # first real prompt instead of surfacing the wrapper text.
    assert meta.prompt_count == 2
    assert meta.ai_title == "Fix the invoice rounding bug in the billing job"


def test_claude_code_ai_title_record_wins_and_last_one_wins():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    path = FIXTURES / "claude_code" / "-Users-me-code-search" / "a1b2c3d4-1111-2222-3333-444455556666.jsonl"
    meta = adapter.read_metadata(path)

    assert meta is not None
    # Two ai-title records in this fixture, no summary, no user-set name —
    # the second (most recent) one should win, not the truncated first
    # prompt and not the first ai-title seen.
    assert meta.ai_title == "Speed up search indexing with a cache layer"


def test_claude_code_cwd_beats_lossy_path_decoder():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    path = FIXTURES / "claude_code" / "-Users-me-code-my-project-v2" / "b2c3d4e5-1111-2222-3333-444455556666.jsonl"
    meta = adapter.read_metadata(path)

    assert meta is not None
    # The directory name encodes the literal "." in "my-project.v2" as "-",
    # which the decoder can't tell apart from a real path separator and
    # would mangle. The real cwd on the transcript line is authoritative.
    assert meta.project == "/Users/me/code/my-project.v2"


def test_claude_code_user_set_name_wins_over_ai_title():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    path = FIXTURES / "claude_code" / "-Users-me-code-notes" / "c3d4e5f6-1111-2222-3333-444455556666.jsonl"
    meta = adapter.read_metadata(path)

    assert meta is not None
    # tests/fixtures/sessions/42.json maps this session id to a user-set
    # name — it should beat the ai-title record present in the same
    # transcript.
    assert meta.ai_title == "tidy the export format"


def test_claude_code_derived_session_name_does_not_win_over_ai_title(tmp_path):
    # Confirmed live against real ~/.claude/sessions/*.json: nameSource
    # "derived" means Claude Code auto-generated the name (e.g.
    # "workspace-a7"), not the user — it must not outrank a real ai-title.
    claude_root = tmp_path / "claude_code"
    project_dir = claude_root / "-Users-me-code-y"
    project_dir.mkdir(parents=True)
    session_id = "e5f6a7b8-1111-2222-3333-444455556666"
    lines = [
        {"type": "user", "sessionId": session_id, "uuid": "1", "parentUuid": None,
         "timestamp": "2026-08-24T13:00:00Z", "message": {"role": "user", "content": "hi"}},
        {"type": "ai-title", "sessionId": session_id, "aiTitle": "Real ai-title"},
    ]
    (project_dir / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "7.json").write_text(
        json.dumps({"pid": 7, "sessionId": session_id, "name": "workspace-xy", "nameSource": "derived"}),
        encoding="utf-8")

    adapter = ClaudeCodeAdapter(claude_root)
    meta = adapter.read_metadata(project_dir / f"{session_id}.jsonl")

    assert meta is not None
    assert meta.ai_title == "Real ai-title"


def test_claude_code_malformed_sessions_file_does_not_break_indexing(tmp_path):
    claude_root = tmp_path / "claude_code"
    project_dir = claude_root / "-Users-me-code-x"
    project_dir.mkdir(parents=True)
    session_id = "d4e5f6a7-1111-2222-3333-444455556666"
    (project_dir / f"{session_id}.jsonl").write_text(
        json.dumps({
            "type": "user", "sessionId": session_id, "uuid": "1", "parentUuid": None,
            "timestamp": "2026-08-24T12:00:00Z",
            "message": {"role": "user", "content": "hello"},
        }) + "\n",
        encoding="utf-8",
    )
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "99.json").write_text("not valid json{{{", encoding="utf-8")

    adapter = ClaudeCodeAdapter(claude_root)
    meta = adapter.read_metadata(project_dir / f"{session_id}.jsonl")

    assert meta is not None
    assert meta.ai_title == "hello"  # falls through cleanly to the first prompt


def test_claude_code_flags_and_redacts_a_probable_secret_in_the_title():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    path = FIXTURES / "claude_code" / "-Users-me-code-secrets-test" / "f6a7b8c9-1111-2222-3333-444455556666.jsonl"
    meta = adapter.read_metadata(path)

    assert meta is not None
    assert meta.secret_hits >= 1
    # Redacted at the source — the raw password never surfaces as a title.
    assert meta.ai_title == "(untitled — possible secret redacted)"
    assert "hunter2" not in (meta.ai_title or "")


def test_claude_code_secret_scan_disableable():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    path = FIXTURES / "claude_code" / "-Users-me-code-secrets-test" / "f6a7b8c9-1111-2222-3333-444455556666.jsonl"
    meta = adapter.read_metadata(path, scan_for_secrets=False)

    assert meta is not None
    assert meta.secret_hits == 0
    assert "password" in (meta.ai_title or "")  # not redacted when scanning is off


def test_codex_lists_session_file():
    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    files = adapter.list_session_files()
    # listing is a cheap fs walk — it includes the subagent rollout file too;
    # filtering that one out happens in read_metadata (see test below).
    names = {f.name for f in files}
    assert names == {
        "rollout-2026-08-22T09-22-56-019e8b13.jsonl",
        "rollout-2026-08-22T09-30-00-11112222.jsonl",
        "rollout-2026-08-22T20-53-44-33334444.jsonl",
    }


def test_codex_skips_wrapper_tag_when_picking_title():
    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    path = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T20-53-44-33334444.jsonl"
    meta = adapter.read_metadata(path)

    assert meta is not None
    assert meta.prompt_count == 2
    assert meta.ai_title == "Add a retry budget to the ingest worker"


def test_codex_metadata_extraction():
    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    path = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    meta = adapter.read_metadata(path)

    assert meta is not None
    assert meta.session_id == "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff"
    assert meta.source == "codex"
    assert meta.project == "/home/me/proj/ingest"
    assert meta.prompt_count == 2
    assert meta.ai_title == "Fix the retry logic in the ingest job"


def test_codex_skips_subagent_sessions():
    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    path = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-30-00-11112222.jsonl"
    assert adapter.read_metadata(path) is None


# --- Phase 7a: Codex SQLite `threads` table enrichment ---


def test_codex_sql_threads_row_overrides_jsonl_metadata(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    build_state_db(codex_home / "state_5.sqlite", [{
        "id": "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff",
        "rollout_path": str(rollout),
        "created_at": 1755856920,   # 2025-08-22T10:02:00Z
        "updated_at": 1755857000,
        "cwd": "/home/me/proj/ingest-from-sql",
        "title": "AI-generated title from SQL",
        "first_user_message": "raw first message",
        "archived": 0,
        "name": None,
        "history_mode": "legacy",
    }])
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)

    assert meta is not None
    assert meta.ai_title == "AI-generated title from SQL"
    assert meta.project == "/home/me/proj/ingest-from-sql"
    assert meta.started_at == "2025-08-22T10:02:00Z"
    # prompt_count stays JSONL-derived in 7a regardless of history_mode.
    assert meta.prompt_count == 2


def test_codex_sql_name_wins_over_title_wins_over_first_user_message(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    build_state_db(codex_home / "state_5.sqlite", [{
        "id": "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff",
        "rollout_path": str(rollout),
        "created_at": None, "updated_at": None,
        "cwd": None,
        "title": "AI title",
        "first_user_message": "first message",
        "archived": 0,
        "name": "my custom name",
        "history_mode": "legacy",
    }])
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)

    assert meta is not None
    assert meta.ai_title == "my custom name"


def test_codex_sql_missing_rollout_path_column_falls_back_cleanly(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    build_state_db_missing_rollout_path_column(codex_home / "state_5.sqlite")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)  # must not raise

    assert meta is not None
    assert meta.ai_title == "Fix the retry logic in the ingest job"  # JSONL-derived baseline, untouched


def test_codex_sql_prefers_newer_mtime_db_over_lexicographic_sort(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    # "state_10" sorts before "state_5" lexicographically — name them so a
    # naive string sort would pick the wrong (older) one.
    older = codex_home / "state_5.sqlite"
    newer = codex_home / "state_10.sqlite"
    build_state_db(older, [{
        "id": "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff", "rollout_path": str(rollout),
        "created_at": None, "updated_at": None, "cwd": None,
        "title": "OLD title", "first_user_message": None,
        "archived": 0, "name": None, "history_mode": "legacy",
    }])
    build_state_db(newer, [{
        "id": "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff", "rollout_path": str(rollout),
        "created_at": None, "updated_at": None, "cwd": None,
        "title": "NEW title", "first_user_message": None,
        "archived": 0, "name": None, "history_mode": "legacy",
    }])
    import os
    import time
    os.utime(older, (time.time() - 100, time.time() - 100))  # deliberately older mtime
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)

    assert meta is not None
    assert meta.ai_title == "NEW title"


# --- Phase 7b: paginated-mode prompt_count from thread_items ---


def test_codex_paginated_prompt_count_comes_from_thread_items_not_jsonl(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    thread_id = "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff"
    build_state_db(codex_home / "state_5.sqlite", [{
        "id": thread_id, "rollout_path": str(rollout),
        "created_at": None, "updated_at": None, "cwd": None,
        "title": None, "first_user_message": None,
        "archived": 0, "name": None, "history_mode": "paginated",
    }])
    # The fixture JSONL has 2 user turns — deliberately make the SQL count
    # disagree (5) so the test actually proves which source wins.
    build_thread_history_db(codex_home / "thread_history_1.sqlite", [
        {"thread_id": thread_id, "item_type": "userMessage"},
        {"thread_id": thread_id, "item_type": "userMessage"},
        {"thread_id": thread_id, "item_type": "userMessage"},
        {"thread_id": thread_id, "item_type": "userMessage"},
        {"thread_id": thread_id, "item_type": "userMessage"},
        {"thread_id": thread_id, "item_type": "agentMessage"},  # not counted
    ])
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)

    assert meta is not None
    assert meta.prompt_count == 5


def test_codex_legacy_mode_prompt_count_stays_jsonl_derived_even_if_thread_history_exists(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    thread_id = "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff"
    build_state_db(codex_home / "state_5.sqlite", [{
        "id": thread_id, "rollout_path": str(rollout),
        "created_at": None, "updated_at": None, "cwd": None,
        "title": None, "first_user_message": None,
        "archived": 0, "name": None, "history_mode": "legacy",
    }])
    # Even if a thread_history DB happens to have rows for this thread,
    # "legacy" mode must never consult it.
    build_thread_history_db(codex_home / "thread_history_1.sqlite", [
        {"thread_id": thread_id, "item_type": "userMessage"},
        {"thread_id": thread_id, "item_type": "userMessage"},
        {"thread_id": thread_id, "item_type": "userMessage"},
    ])
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)

    assert meta is not None
    assert meta.prompt_count == 2  # the fixture JSONL's real count, unchanged


def test_codex_paginated_mode_falls_back_to_jsonl_count_when_thread_absent_from_thread_items(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    build_state_db(codex_home / "state_5.sqlite", [{
        "id": "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff", "rollout_path": str(rollout),
        "created_at": None, "updated_at": None, "cwd": None,
        "title": None, "first_user_message": None,
        "archived": 0, "name": None, "history_mode": "paginated",
    }])
    # No thread_history_*.sqlite at all — GROUP BY would have nothing for
    # this thread_id even if one existed. Absence must resolve to the JSONL
    # count, not zero and not a crash.
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)

    assert meta is not None
    assert meta.prompt_count == 2


def test_codex_unrecognized_history_mode_keeps_jsonl_prompt_count(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    thread_id = "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff"
    build_state_db(codex_home / "state_5.sqlite", [{
        "id": thread_id, "rollout_path": str(rollout),
        "created_at": None, "updated_at": None, "cwd": None,
        "title": None, "first_user_message": None,
        "archived": 0, "name": None, "history_mode": "some_future_mode",
    }])
    build_thread_history_db(codex_home / "thread_history_1.sqlite", [
        {"thread_id": thread_id, "item_type": "userMessage"},
    ])
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)

    assert meta is not None
    assert meta.prompt_count == 2  # not the SQLite count of 1 — only "paginated" is handled


def test_codex_sql_title_is_still_redacted_if_it_looks_like_a_secret(tmp_path, monkeypatch):
    rollout = FIXTURES / "codex_sessions" / "2026" / "08" / "22" / "rollout-2026-08-22T09-22-56-019e8b13.jsonl"
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    build_state_db(codex_home / "state_5.sqlite", [{
        "id": "019e8b13-aaaa-bbbb-cccc-ddddeeeeffff", "rollout_path": str(rollout),
        "created_at": None, "updated_at": None, "cwd": None,
        "title": "the api_key=sk-abc123 leaked", "first_user_message": None,
        "archived": 0, "name": None, "history_mode": "legacy",
    }])
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    meta = adapter.read_metadata(rollout)

    assert meta is not None
    assert meta.ai_title == "(untitled — possible secret redacted)"


def test_missing_root_returns_empty_list():
    adapter = ClaudeCodeAdapter(FIXTURES / "does_not_exist")
    assert adapter.list_session_files() == []
