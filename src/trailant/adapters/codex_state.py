"""Read-only access to Codex CLI's SQLite session index.

Codex (as of the v0.149.1 install this was verified against) uses a hybrid
storage model, confirmed by direct SQL introspection and by asking the real
`codex` CLI to introspect its own installation:

  - `$CODEX_HOME` (default `~/.codex`) holds `state_*.sqlite` — the numeric
    suffix is version-specific, never assume a fixed one — with a `threads`
    table, one row per session: id, rollout_path, timestamps, cwd, an
    AI-generated `title`, `first_user_message`, a user-settable `name`, and
    `history_mode` ("legacy" or "paginated", observed).
  - `rollout_path` points to a real, still-existing legacy-format JSONL file
    in BOTH modes — verified directly on a brand-new paginated-mode thread.
    This is what keeps codex.py's file-based discovery/caching untouched:
    only read_metadata()'s internals change, never list_session_files().

This module only ever reads. Opened as `file:...?mode=ro` (not
`immutable=1`, which can serve stale data while Codex is actively writing
via WAL — exactly the "is this session active right now" case trailant
cares about). Every failure mode here (missing CODEX_HOME, no state DB —
an older Codex install, a renamed/missing column — a schema change) must
degrade to an empty result, never raise past this module: the schema has
no stability contract, and callers fall back to JSONL-only parsing on any
miss.
"""
from __future__ import annotations

import os
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Optional

_THREAD_COLUMNS = [
    "id", "rollout_path", "cwd", "title", "first_user_message",
    "created_at", "updated_at", "history_mode", "name", "archived",
]


def codex_home() -> Path:
    """Codex's own data root. Respects $CODEX_HOME (Codex's own env var,
    distinct from trailant's TRAILANT_HOME) before falling back to ~/.codex."""
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex"


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    # uri=True is required for "file:...?mode=ro" to be parsed as a URI at
    # all — without it sqlite3 treats the whole string as a literal
    # filename (silently creating one, the opposite of read-only). The path
    # itself needs percent-encoding: a raw f-string breaks on spaces, "#",
    # or "%" in $CODEX_HOME, all realistic on a real machine.
    uri = f"file:{urllib.parse.quote(db_path.as_posix())}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def load_threads_index(home: Optional[Path] = None) -> dict[str, dict]:
    """Best-effort {normalized rollout_path: thread row dict}. Empty dict on
    any failure — every miss falls through to today's JSONL-only parsing,
    unchanged from before this module existed."""
    home = home or codex_home()
    index: dict[str, dict] = {}
    try:
        db_files = sorted(home.glob("state_*.sqlite"), key=lambda f: f.stat().st_mtime)
    except OSError:
        return index

    # Oldest first: a later file's row for the same rollout_path overwrites
    # an earlier one. Sorted by mtime, not filename — "state_10.sqlite"
    # sorts before "state_5.sqlite" as a string, which is backwards from
    # "which file is actually newer" if Codex ever leaves a stale DB behind
    # across an upgrade.
    for db_path in db_files:
        try:
            conn = _ro_connect(db_path)
        except sqlite3.Error:
            continue
        try:
            cols = _table_columns(conn, "threads")
            if "rollout_path" not in cols:
                continue
            select_cols = [c for c in _THREAD_COLUMNS if c in cols]
            rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM threads").fetchall()
            for row in rows:
                d = dict(zip(select_cols, row))
                rp = d.get("rollout_path")
                if rp:
                    index[str(Path(rp).expanduser())] = d
        except sqlite3.Error:
            continue
        finally:
            conn.close()
    return index
