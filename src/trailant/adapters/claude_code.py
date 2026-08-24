"""Adapter for Claude Code session logs.

Format (as of Aug 2026): one .jsonl per session at
    ~/.claude/projects/<project-path-with-/-replaced-by-->/<session-id>.jsonl

Each line is a JSON object with `type`, `sessionId`, `uuid`, `parentUuid`, and
(for user/assistant lines) a `message` object with `role`/`content`. Lines
are chained via uuid/parentUuid, but for cheap metadata extraction we only
need line order, not the full chain.

Title precedence (highest to lowest — verified against real transcripts,
see git history for the Windows validation that found this): a user-set
session display name from `~/.claude/sessions/*.json`, then the most recent
`type: "ai-title"` record's `aiTitle` field, then a legacy `type: "summary"`
record (kept as a fallback for older transcripts — real transcripts checked
during this fix had zero of these, but it costs nothing to keep), then the
first non-wrapper user prompt, truncated. `type: "summary"` was previously
treated as the *primary* source and silently never matched anything.

`cwd` is read directly from the transcript when present (most lines carry
it) — authoritative, no decoding needed. `_decode_project_path` is now a
fallback only, for the rare line that lacks it. It remains lossy (Claude
Code's directory-name encoding maps `:`, `\\`, `/`, and `.` all to `-`,
which is irreversible on Windows paths in particular).

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
from ..utils import is_system_wrapper_text, looks_like_secret


class ClaudeCodeAdapter(SourceAdapter):
    name = "claude_code"

    def __init__(self, root: Path):
        super().__init__(root)
        self._session_names: Optional[dict[str, str]] = None

    def list_session_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        # root/<project-dir>/<session-id>.jsonl — exactly one level deep.
        return sorted(self.root.glob("*/*.jsonl"))

    def _get_session_names(self) -> dict[str, str]:
        """Lazily scanned once per adapter instance (i.e. at most once per
        reindex() run, since indexer.py reuses one adapter across all
        files) — and skipped entirely if every file in a run is a cache
        hit, since nothing calls this unless read_metadata() runs."""
        if self._session_names is None:
            self._session_names = self._load_session_names()
        return self._session_names

    def _load_session_names(self) -> dict[str, str]:
        """Best-effort scan of ~/.claude/sessions/*.json for user-set
        session display names (Claude Code's -n/--name, or the picker's
        rename). Vendor-internal, no stability contract — any failure here
        must degrade to "no names found", never break indexing.

        Excludes nameSource == "derived": confirmed live against real
        session files that these are Claude Code's own auto-generated
        fallback slugs (e.g. "workspace-a7"), not something the user chose
        — letting them win would rank a weak auto-slug above a real
        ai-title record, the opposite of the intended precedence."""
        names: dict[str, str] = {}
        sessions_dir = self.root.parent / "sessions"
        if not sessions_dir.exists():
            return names
        try:
            candidates = sorted(sessions_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
        except OSError:
            return names
        for f in candidates:
            try:
                data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            session_id, name = data.get("sessionId"), data.get("name")
            if session_id and isinstance(name, str) and name and data.get("nameSource") != "derived":
                names[session_id] = name  # sorted by mtime — most-recent file wins on collision
        return names

    def _decode_project_path(self, project_dir_name: str) -> str:
        # Claude Code encodes the project's absolute path by replacing "/" with "-".
        # This is a lossy decode (a literal "-" in a real path is ambiguous with a
        # path separator) but good enough for display purposes.
        if project_dir_name.startswith("-"):
            return "/" + project_dir_name[1:].replace("-", "/")
        return project_dir_name.replace("-", "/")

    def read_metadata(self, path: Path, *, scan_for_secrets: bool = True) -> Optional[SessionMeta]:
        try:
            stat = path.stat()
        except OSError:
            return None

        session_id = path.stem
        decoded_project = self._decode_project_path(path.parent.name)

        prompt_count = 0
        first_user_text: Optional[str] = None
        first_ts: Optional[str] = None
        last_ts: Optional[str] = None
        summary_title: Optional[str] = None
        ai_title_record: Optional[str] = None
        cwd_from_record: Optional[str] = None
        secret_hits = 0

        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if scan_for_secrets and looks_like_secret(line):
                        secret_hits += 1
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = record.get("timestamp")
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts

                    if cwd_from_record is None:
                        cwd = record.get("cwd")
                        if cwd:
                            cwd_from_record = cwd

                    rtype = record.get("type")
                    if rtype == "ai-title":
                        # Titles can regenerate mid-session — last one wins,
                        # not first.
                        at = record.get("aiTitle")
                        if at:
                            ai_title_record = at
                    elif rtype == "summary" and record.get("summary"):
                        summary_title = record["summary"]
                    elif rtype == "user":
                        prompt_count += 1
                        if first_user_text is None:
                            message = record.get("message", {})
                            content = message.get("content")
                            text: Optional[str] = None
                            if isinstance(content, str):
                                text = content
                            elif isinstance(content, list) and content:
                                # content blocks: take first text-like block
                                block = content[0]
                                if isinstance(block, dict):
                                    text = block.get("text")
                            if text and not is_system_wrapper_text(text):
                                first_user_text = text
        except OSError:
            return None

        project = cwd_from_record or decoded_project

        first_prompt_title = (
            (first_user_text[:80] + "...") if first_user_text and len(first_user_text) > 80
            else first_user_text
        )
        user_name = self._get_session_names().get(session_id)
        ai_title = user_name or ai_title_record or summary_title or first_prompt_title
        if ai_title and scan_for_secrets and looks_like_secret(ai_title):
            # Redact at the source: ai_title flows into resume/status/--html/
            # diff unchanged, so fixing it here protects every consumer at
            # once instead of needing separate redaction logic downstream.
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
        )
