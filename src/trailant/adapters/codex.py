"""Adapter for Codex CLI session logs.

Format (as of Aug 2026): one .jsonl per session, date-sharded, at
    ~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl

The first line is a `session_meta` record with a `payload` containing at
least `id`, `cwd`, and `model_provider`. Remaining lines are `response_item`
records; conversational ones have `payload.role` ("user"/"assistant") and
`payload.content` (a list of blocks with `type`/`text`).

Codex also maintains a SQLite session index (see codex_state.py) alongside
these JSONL files — confirmed by direct SQL introspection and by asking the
real `codex` CLI to introspect its own installation (v0.149.1). It's a
hybrid, not a full migration: every real thread checked (both "legacy" and
"paginated" `history_mode`) still has a real rollout_path JSONL file, so
list_session_files() and indexer.py's mtime/size caching stay untouched —
only read_metadata() additionally checks the SQLite index and, when a
match is found, prefers its title/cwd/timestamps (Codex's own AI-generated
title, real cwd, no parsing needed) over what JSONL parsing derives. Any
miss — no state DB, older Codex, a renamed column, any unexpected shape —
falls back to the JSONL-only baseline below exactly as before this existed.
prompt_count stays JSONL-derived regardless of history_mode for now; the
paginated-mode SQLite prompt count (`thread_items`, cheaper and
authoritative) is a deliberate fast-follow, not bundled in here, since a
wrong prompt count would quietly corrupt `cadence`'s trend, a materially
worse failure than a wrong title.

Notes carried over from the technical overview:
  - Codex's own /resume list filters sessions by `model_provider` matching the
    currently configured provider. This adapter intentionally does NOT filter
    by provider — trailant wants the superset view across everything you've
    ever run, regardless of which provider was active at the time.
  - Subagent sessions live as separate files in the same date directory as
    their parent, distinguished by `source: "subagent"` in their own
    session_meta. These ARE filtered out here (return None) — counting them
    as top-level sessions would inflate prompt/session counts that `cadence`
    depends on.
  - Some inactive sessions may be compressed to `.jsonl.zst`. This starter
    adapter skips those (returns None) rather than adding a zstandard
    dependency; decompression support is a natural first contribution (and,
    for a paginated-mode thread, reconstructable from SQLite without ever
    decompressing — not yet implemented, see the roadmap).
  - Sessions can be very large (compaction history can push files into the
    hundreds of MB). read_metadata() only reads what it needs, but on very
    large files even that is an O(file size) scan — measured directly
    against a real 209MB Claude Code transcript at 0.44s, not currently
    acute given indexer.py's existing mtime/size caching; deliberately
    deferred rather than rushed (see CONTRIBUTING.md).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import SourceAdapter
from .codex_state import load_threads_index
from ..models import SessionMeta
from ..utils import is_system_wrapper_text, looks_like_secret


def _epoch_to_iso(unix_seconds) -> Optional[str]:
    try:
        return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError):
        return None


class CodexAdapter(SourceAdapter):
    name = "codex"

    def __init__(self, root: Path):
        super().__init__(root)
        self._threads_index: Optional[dict] = None

    def list_session_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.rglob("rollout-*.jsonl"))

    def _get_threads_index(self) -> dict:
        """Lazily loaded once per adapter instance (i.e. at most once per
        reindex() run, since indexer.py reuses one adapter across all
        files) — skipped entirely if every file in a run is a cache hit.
        Same pattern as claude_code.py's _get_session_names()."""
        if self._threads_index is None:
            self._threads_index = load_threads_index()
        return self._threads_index

    def read_metadata(self, path: Path, *, scan_for_secrets: bool = True) -> Optional[SessionMeta]:
        if path.suffix == ".zst":
            return None  # compressed — see module docstring

        try:
            stat = path.stat()
        except OSError:
            return None

        session_id = path.stem
        project = ""
        prompt_count = 0
        first_user_text: Optional[str] = None
        first_ts: Optional[str] = None
        last_ts: Optional[str] = None
        secret_hits = 0

        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    if scan_for_secrets and looks_like_secret(line):
                        secret_hits += 1
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    rtype = record.get("type")
                    payload = record.get("payload", {})

                    if rtype == "session_meta":
                        if payload.get("source") == "subagent":
                            return None
                        session_id = payload.get("id", session_id)
                        project = payload.get("cwd", "")
                        ts = payload.get("timestamp")
                        if ts:
                            first_ts = ts
                        continue

                    if rtype == "response_item":
                        ts = record.get("timestamp") or payload.get("timestamp")
                        if ts:
                            if first_ts is None:
                                first_ts = ts
                            last_ts = ts

                        if payload.get("role") == "user":
                            prompt_count += 1
                            if first_user_text is None:
                                content = payload.get("content")
                                if isinstance(content, list) and content:
                                    block = content[0]
                                    if isinstance(block, dict):
                                        text = block.get("text")
                                        if text and not is_system_wrapper_text(text):
                                            first_user_text = text
        except OSError:
            return None

        first_prompt_title = (
            (first_user_text[:80] + "...") if first_user_text and len(first_user_text) > 80
            else first_user_text
        )

        # SQL enrichment (Phase 7a) — isolated from the JSONL-derived baseline
        # above, which stays independently correct. Any unexpected shape
        # here (schema drift, a column meaning something different than
        # expected) must fall back to that baseline silently, never abort
        # read_metadata for the whole file.
        archived = False
        sql_title = None
        thread = self._get_threads_index().get(str(path))
        if thread is None:
            thread = self._get_threads_index().get(str(path.resolve()))
        if thread is not None:
            try:
                session_id = thread.get("id") or session_id
                project = thread.get("cwd") or project
                sql_first_ts = _epoch_to_iso(thread.get("created_at"))
                if sql_first_ts:
                    first_ts = sql_first_ts
                sql_last_ts = _epoch_to_iso(thread.get("updated_at"))
                if sql_last_ts:
                    last_ts = sql_last_ts
                sql_title = thread.get("name") or thread.get("title") or thread.get("first_user_message")
                archived = bool(thread.get("archived"))
            except Exception:
                sql_title = None
                archived = False

        ai_title = sql_title or first_prompt_title
        if ai_title and scan_for_secrets and looks_like_secret(ai_title):
            ai_title = "(untitled — possible secret redacted)"

        return SessionMeta(
            session_id=session_id,
            source=self.name,
            project=project,
            started_at=first_ts,
            ended_at=last_ts,
            prompt_count=prompt_count,
            size_bytes=stat.st_size,
            file_path=str(path),
            file_mtime=stat.st_mtime,
            ai_title=ai_title,
            secret_hits=secret_hits,
            archived=archived,
        )
