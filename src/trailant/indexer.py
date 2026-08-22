"""Ties adapters together and maintains trails.jsonl.

The core trick, per the technical overview: stat() every known session file
on every run (cheap, even at thousands of files), and only ask the adapter
to re-parse a file's contents when its mtime or size has changed since the
last time we looked. Unchanged files are trusted as-is — "the trail hasn't
moved, no need to re-walk it."
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import jsonl_store
from .adapters import ADAPTERS
from .config import enabled_sources, trailant_home


@dataclass
class ReindexResult:
    scanned: int = 0
    unchanged: int = 0
    updated: int = 0
    skipped: int = 0


def trails_path() -> Path:
    return trailant_home() / "trails.jsonl"


def reindex(config: dict) -> ReindexResult:
    path = trails_path()
    existing = {r["file_path"]: r for r in jsonl_store.read_all(path)}
    result_records = dict(existing)
    result = ReindexResult()

    for source_name, root in enabled_sources(config).items():
        adapter_cls = ADAPTERS.get(source_name)
        if adapter_cls is None:
            continue
        adapter = adapter_cls(root)

        for file in adapter.list_session_files():
            result.scanned += 1
            try:
                stat = file.stat()
            except OSError:
                result.skipped += 1
                continue

            key = str(file)
            cached = existing.get(key)
            if (
                cached
                and cached.get("file_mtime") == stat.st_mtime
                and cached.get("size_bytes") == stat.st_size
            ):
                result.unchanged += 1
                continue

            meta = adapter.read_metadata(file)
            if meta is None:
                result.skipped += 1
                continue

            result_records[key] = meta.to_dict()
            result.updated += 1

    jsonl_store.write_all(path, result_records.values())
    return result


def load_trails() -> list[dict]:
    return jsonl_store.read_all(trails_path())
