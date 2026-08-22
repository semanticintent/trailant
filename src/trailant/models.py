"""The normalized shapes every adapter produces, and every downstream command consumes.

Keeping these as plain dataclasses (not vendor-specific) is what lets `resume`,
`today`, `week`, and `cadence` stay vendor-agnostic — they only ever see a
SessionMeta, never a raw Claude Code or Codex record.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class SessionMeta:
    session_id: str
    source: str                 # "claude_code" | "codex" | future vendors
    project: str                # cwd / project path as reported by the vendor
    started_at: Optional[str]   # ISO 8601, may be None if not derivable cheaply
    ended_at: Optional[str]
    prompt_count: int
    size_bytes: int
    file_path: str
    file_mtime: float
    ai_title: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "SessionMeta":
        return SessionMeta(**d)


@dataclass
class Mark:
    date: str          # YYYY-MM-DD
    kind: str           # "session_close" | "self_log" | "timesheet_day"
    content: str
    session_id: Optional[str] = None
    sent_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Mark":
        return Mark(**d)
