"""Ties adapters together and maintains trails.jsonl.

The core trick, per the technical overview: stat() every known session file
on every run (cheap, even at thousands of files), and only ask the adapter
to re-parse a file's contents when its mtime or size has changed since the
last time we looked. Unchanged files are trusted as-is — "the trail hasn't
moved, no need to re-walk it."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import jsonl_store
from .adapters import ADAPTERS
from .config import enabled_sources, trailant_home

# Bumped whenever adapter extraction logic changes in a way that should
# force re-parsing of already-indexed, unchanged files — otherwise the
# mtime/size cache below would keep serving stale metadata (e.g. an old
# title) forever, since nothing about the source file itself changed.
INDEX_SCHEMA_VERSION = 6


@dataclass
class SourceCoverage:
    """Per-source counterpart to ReindexResult — lets `reindex` report which
    source a skipped/unchanged/updated file belonged to, not just an
    aggregate total. A source that's configured but silently finds nothing
    (root moved, vendor changed its storage format) is exactly the kind of
    regression an aggregate-only count would hide."""
    root: str = ""
    scanned: int = 0
    unchanged: int = 0
    updated: int = 0
    skipped: int = 0


@dataclass
class ReindexResult:
    scanned: int = 0
    unchanged: int = 0
    updated: int = 0
    skipped: int = 0
    by_source: dict[str, SourceCoverage] = field(default_factory=dict)


def trails_path() -> Path:
    return trailant_home() / "trails.jsonl"


def reindex(config: dict) -> ReindexResult:
    path = trails_path()
    existing = {r["file_path"]: r for r in jsonl_store.read_all(path)}
    result_records = dict(existing)
    result = ReindexResult()
    scan_for_secrets = config.get("secrets", {}).get("enabled", True)

    for source_name, root in enabled_sources(config).items():
        adapter_cls = ADAPTERS.get(source_name)
        if adapter_cls is None:
            continue
        adapter = adapter_cls(root)
        cov = result.by_source.setdefault(source_name, SourceCoverage(root=str(root)))

        for file in adapter.list_session_files():
            result.scanned += 1
            cov.scanned += 1
            try:
                stat = file.stat()
            except OSError:
                result.skipped += 1
                cov.skipped += 1
                continue

            key = str(file)
            cached = existing.get(key)
            if (
                cached
                and cached.get("file_mtime") == stat.st_mtime
                and cached.get("size_bytes") == stat.st_size
                and cached.get("_index_schema_version") == INDEX_SCHEMA_VERSION
            ):
                result.unchanged += 1
                cov.unchanged += 1
                continue

            meta = adapter.read_metadata(file, scan_for_secrets=scan_for_secrets)
            if meta is None:
                result.skipped += 1
                cov.skipped += 1
                continue

            record = meta.to_dict()
            record["_index_schema_version"] = INDEX_SCHEMA_VERSION
            result_records[key] = record
            result.updated += 1
            cov.updated += 1

    jsonl_store.write_all(path, result_records.values())
    return result


def load_trails() -> list[dict]:
    return jsonl_store.read_all(trails_path())
