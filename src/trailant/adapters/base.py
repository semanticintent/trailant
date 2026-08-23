"""The adapter contract. Every vendor adapter (Claude Code, Codex, future ones)
implements this and nothing outside adapters/ should need to know vendor-specific
file formats. That boundary is what keeps adding a new vendor a self-contained change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..models import SessionMeta


class SourceAdapter(ABC):
    name: str = "base"

    def __init__(self, root: Path):
        self.root = root

    @abstractmethod
    def list_session_files(self) -> list[Path]:
        """Cheap filesystem walk. No parsing of file contents here."""
        raise NotImplementedError

    @abstractmethod
    def read_metadata(self, path: Path) -> Optional[SessionMeta]:
        """Read the minimum bytes needed to produce a SessionMeta.
        Return None (rather than raising) for files that can't be parsed —
        callers should skip and warn, not crash the whole reindex."""
        raise NotImplementedError

    def read_full_text(self, path: Path) -> str:
        """Full parse, for on-demand use (e.g. drafting a self-log summary).
        Default implementation just reads the file; adapters with structured
        formats may want to override this to return a cleaner transcript."""
        return path.read_text(encoding="utf-8", errors="replace")
