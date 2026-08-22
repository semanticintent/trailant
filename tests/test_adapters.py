from pathlib import Path

from trailant.adapters.claude_code import ClaudeCodeAdapter
from trailant.adapters.codex import CodexAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def test_claude_code_lists_session_file():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    files = adapter.list_session_files()
    assert len(files) == 1
    assert files[0].name == "db4961c3-1111-2222-3333-444455556666.jsonl"


def test_claude_code_metadata_extraction():
    adapter = ClaudeCodeAdapter(FIXTURES / "claude_code")
    files = adapter.list_session_files()
    meta = adapter.read_metadata(files[0])

    assert meta is not None
    assert meta.session_id == "db4961c3-1111-2222-3333-444455556666"
    assert meta.source == "claude_code"
    assert meta.project == "/Users/me/code/ingest"
    assert meta.prompt_count == 2
    assert meta.started_at == "2026-08-22T09:14:00Z"
    assert meta.ended_at == "2026-08-22T11:02:00Z"
    # summary line should win over the truncated first-message fallback
    assert meta.ai_title == "Refactor session-resume report parser"


def test_codex_lists_session_file():
    adapter = CodexAdapter(FIXTURES / "codex_sessions")
    files = adapter.list_session_files()
    # listing is a cheap fs walk — it includes the subagent rollout file too;
    # filtering that one out happens in read_metadata (see test below).
    names = {f.name for f in files}
    assert names == {
        "rollout-2026-08-22T09-22-56-019e8b13.jsonl",
        "rollout-2026-08-22T09-30-00-11112222.jsonl",
    }


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
