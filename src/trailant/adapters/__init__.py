from .base import SourceAdapter
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter

# Registry — add new adapters here as they're written.
ADAPTERS: dict[str, type[SourceAdapter]] = {
    "claude_code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
}

__all__ = ["SourceAdapter", "ClaudeCodeAdapter", "CodexAdapter", "ADAPTERS"]
