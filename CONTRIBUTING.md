# Contributing to trailant

This started as a personal tool and is being open-sourced early and rough on purpose — the
architecture (JSONL source of truth, disposable cache, vendor adapters) is the part meant to be
solid; a lot of the rest is a starting point, not a finished product.

## Status of this starter scaffold

Implemented and tested (`pytest` passes, CLI smoke-tested against fixture data):

- Config loading + first-run bootstrap (`src/trailant/config.py`)
- JSONL append/upsert/write-all store (`src/trailant/jsonl_store.py`)
- Claude Code adapter, tested against a realistic fixture
- Codex adapter, tested against a realistic fixture
- mtime/size-gated reindexing (`src/trailant/indexer.py`)
- CLI commands: `reindex`, `resume`, `status`, `log`, `close`, `today`, `week`, `cadence`

## Known limitations / good first issues

1. **Timezone handling is naive.** `today`/`week` compare a local calendar date against
   vendor timestamps that are typically UTC (`best_effort_date` in `utils.py` just slices the
   first 10 characters of an ISO string). This will misfile sessions run near midnight local
   time. Needs proper timezone-aware comparison, probably with a configurable local timezone.
2. **No `.jsonl.zst` (compressed Codex session) support.** `CodexAdapter.read_metadata` returns
   `None` for these today. Decompressing requires the `zstandard` package, deliberately not added
   yet to keep the dependency footprint minimal — worth reconsidering once it's a real gap in
   people's data.
3. **Codex adapter reads full file contents for metadata**, even though only the first
   (`session_meta`) line is strictly required for most fields — prompt count and title currently
   require a full scan. For very large rollout files (some have been observed in the hundreds of
   MB to low GB range) this is the main performance risk. A tail-seek or streaming approach that
   stops early once title/count are found would help.
4. **`trailant close` has no working `send_via`.** It drafts and saves a mark locally but does not
   actually send anywhere — the Outlook/email integration described in the technical overview is
   intentionally left as a pluggable external hook, not part of the open-source core.
5. **No SQLite cache tier yet**, by design (see `docs/technical-overview.md` §2-3, §9) — only
   add one once `resume`/`cadence` are demonstrably slow at real-world trail counts, not before.
6. **Claude Code project path decoding is lossy.** Directory names encode `/` as `-`, so a project
   path that itself contains a literal `-` can't be perfectly reconstructed. Fine for display,
   worth flagging if it ever needs to be used for anything write-back-capable.
7. **No adapters yet for Cursor, Gemini CLI, or other vendors.** The adapter interface
   (`src/trailant/adapters/base.py`) is meant to make this a self-contained addition — a new
   adapter module, a registry entry in `adapters/__init__.py`, and fixtures/tests mirroring the
   existing two.

## Running tests

```bash
pip install -e ".[dev]"   # or: pip install -e . && pip install pytest
pytest -v
```

## Testing the CLI against fixture data without touching real session files

```bash
export TRAILANT_HOME=/tmp/trailant_dev
mkdir -p $TRAILANT_HOME
cat > $TRAILANT_HOME/config.yaml << EOF
sources:
  claude_code:
    enabled: true
    root: $(pwd)/tests/fixtures/claude_code
  codex:
    enabled: true
    root: $(pwd)/tests/fixtures/codex_sessions
EOF
trailant reindex
trailant resume
```

`TRAILANT_HOME` is respected everywhere config/data are read, specifically so this kind of
isolated testing is possible without ever pointing the tool at a real `~/.claude` or `~/.codex`.
