import json
from pathlib import Path

from trailant.adapters.claude_code import ClaudeCodeAdapter
from trailant.adapters.codex import CodexAdapter

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_missing_root_returns_empty_list():
    adapter = ClaudeCodeAdapter(FIXTURES / "does_not_exist")
    assert adapter.list_session_files() == []
