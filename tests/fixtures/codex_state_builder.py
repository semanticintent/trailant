"""Builds fixture Codex SQLite state DBs at test time — CREATE TABLE/INSERT,
no checked-in binaries. A binary .sqlite fixture would be undiffable and
schema drift would be invisible in review, the opposite of this project's
plain-text-over-opaque philosophy.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def build_state_db(db_path: Path, threads: list[dict]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                cwd TEXT,
                title TEXT,
                first_user_message TEXT,
                archived INTEGER,
                name TEXT,
                history_mode TEXT
            )
        """)
        for t in threads:
            cols = ", ".join(t)
            placeholders = ", ".join("?" for _ in t)
            conn.execute(f"INSERT INTO threads ({cols}) VALUES ({placeholders})", list(t.values()))
        conn.commit()
    finally:
        conn.close()


def build_state_db_missing_rollout_path_column(db_path: Path) -> None:
    """Simulates schema drift: a threads table that exists but doesn't even
    have the one column this adapter absolutely requires."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, cwd TEXT)")
        conn.execute("INSERT INTO threads (id, cwd) VALUES ('x', '/tmp')")
        conn.commit()
    finally:
        conn.close()
