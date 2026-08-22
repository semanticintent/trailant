"""Adapter for Claude Code session logs.

Format (as of Aug 2026): one .jsonl per session at
    ~/.claude/projects/<project-path-with-/-replaced-by-->/<session-id>.jsonl

Each line is a JSON object with `type`, `sessionId`, `uuid`, `parentUuid`, and
(for user/assistant lines) a `message` object with `role`/`content`. Lines
are chained via uuid/parentUuid, but for cheap metadata extraction we only
need line order, not the full chain.

Sub-agent transcripts live in a sibling `<session-id>/subagents/` directory
and are intentionally NOT picked up by list_session_files() here — the glob
pattern only matches files one level under a project directory, which
sub-agent files (nested one level deeper) don't satisfy.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .base import SourceAdapter
from ..models import SessionMeta


class ClaudeCodeAdapter(SourceAdapter):
    name = "claude_code"

    def list_session_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        # root/<project-dir>/<session-id>.jsonl — exactly one level deep.
        return sorted(self.root.glob("*/*.jsonl"))

    def _decode_project_path(self, project_dir_name: str) -> str:
        # Claude Code encodes the project's absolute path by replacing "/" with "-".
        # This is a lossy decode (a literal "-" in a real path is ambiguous with a
        # path separator) but good enough for display purposes.
        if project_dir_name.startswith("-"):
            return "/" + project_dir_name[1:].replace("-", "/")
        return project_dir_name.replace("-", "/")

    def read_metadata(self, path: Path) -> Optional[SessionMeta]:
        try:
            stat = path.stat()
        except OSError:
            return None

        session_id = path.stem
        project = self._decode_project_path(path.parent.name)

        prompt_count = 0
        first_user_text: Optional[str] = None
        first_ts: Optional[str] = None
        last_ts: Optional[str] = None
        summary_title: Optional[str] = None

        try:
            with path.open(errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = record.get("timestamp")
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts

                    rtype = record.get("type")
                    if rtype == "summary" and record.get("summary"):
                        summary_title = record["summary"]
                    elif rtype == "user":
                        prompt_count += 1
                        if first_user_text is None:
                            message = record.get("message", {})
                            content = message.get("content")
                            if isinstance(content, str):
                                first_user_text = content
                            elif isinstance(content, list) and content:
                                # content blocks: take first text-like block
                                block = content[0]
                                if isinstance(block, dict):
                                    first_user_text = block.get("text")
        except OSError:
            return None

        ai_title = summary_title or (
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
