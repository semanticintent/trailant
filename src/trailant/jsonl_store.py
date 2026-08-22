"""Minimal append-only JSONL store.

This is deliberately dumb: read the whole file into memory, write the whole
file back out. That's fine for a personal tool at the scale of thousands of
sessions/marks. If it ever stops being fine, that's the signal to introduce
the SQLite cache described in the technical overview — not before.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open() as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Never let one corrupt line take down the whole read.
                # A real implementation should log this; kept quiet here to
                # keep the starter scaffold dependency-free.
                continue
    return records


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_all(path: Path, records: Iterable[dict]) -> None:
    """Overwrite the file entirely with the given records, one per line.
    Used by reindex, which computes the full desired state in memory first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
