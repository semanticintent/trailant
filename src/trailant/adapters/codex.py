"""Adapter for Codex CLI session logs.

Format (as of Aug 2026): one .jsonl per session, date-sharded, at
    ~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl

The first line is a `session_meta` record with a `payload` containing at
least `id`, `cwd`, and `model_provider`. Remaining lines are `response_item`
records; conversational ones have `payload.role` ("user"/"assistant") and
`payload.content` (a list of blocks with `type`/`text`).

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
    dependency; decompression support is a natural first contribution.
  - Sessions can be very large (compaction history can push files into the
    hundreds of MB). read_metadata() only reads what it needs, but on very
    large files even that is an O(file size) scan — a future optimization
    is to only read the first line (session_meta) plus a tail seek, rather
    than the full file, once titles/counts need to come from elsewhere.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .base import SourceAdapter
from ..models import SessionMeta


class CodexAdapter(SourceAdapter):
    name = "codex"

    def list_session_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.rglob("rollout-*.jsonl"))

    def read_metadata(self, path: Path) -> Optional[SessionMeta]:
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

        try:
            with path.open(errors="replace") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
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
                                        first_user_text = block.get("text")
        except OSError:
            return None

        ai_title = (
            (first_user_text[:80] + "...") if first_user_text and len(first_user_text) > 80
            else first_user_text
        )

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
        )
