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
- mtime/size-gated reindexing, with a schema-version stamp that forces a one-time
  re-parse of already-indexed files when adapter extraction logic changes (`src/trailant/indexer.py`)
- Cross-platform CI (ubuntu/macos/windows × Python 3.10/3.12) plus a Windows-console-encoding
  regression test that doesn't require an actual Windows machine to run
- CLI commands: `reindex`, `diff`, `resume` (`--html`, `--print-command`), `status`, `log`, `close`,
  `today`, `week`, `cadence` (`--html`)

## Known limitations / good first issues

1. **Timezone handling is naive.** `today`/`week` compare a local calendar date against
   vendor timestamps that are typically UTC (`best_effort_date` in `utils.py` just slices the
   first 10 characters of an ISO string). This will misfile sessions run near midnight local
   time. Needs proper timezone-aware comparison, probably with a configurable local timezone.
2. **No `.jsonl.zst` (compressed Codex session) support.** `CodexAdapter.read_metadata` returns
   `None` for these today. Decompressing requires the `zstandard` package, deliberately not added
   yet to keep the dependency footprint minimal — worth reconsidering once it's a real gap in
   people's data.
3. **Both adapters read full file contents for metadata**, even though only the first line or
   two is strictly required for some fields — prompt count and `ended_at` genuinely need a full
   scan (every line can update them), so a naive "stop after N lines" bound would silently
   truncate those on any real session past that bound, and Phase 2's activity-based reporting
   (`status`/`today`/`week`/`cadence`) leans on `ended_at` being accurate. Measured directly
   against a real 209MB Claude Code transcript: 0.44s — not the crisis a truncated-read fix would
   imply, since `reindex`'s mtime/size cache already means this cost is only paid once per file
   that actually changed, not on every run. The real fix here is incremental (persist a byte
   offset and running aggregates, resume from there on the next changed-file scan) rather than a
   lossy line-count bound — genuinely valuable for a transcript that grows across many sessions
   over a long career, just not an acute problem at today's usage scale. Deliberately deferred
   rather than rushed.
4. **`trailant close` has no working `send_via`.** It drafts and saves a mark locally but does not
   actually send anywhere — the Outlook/email integration described in the technical overview is
   intentionally left as a pluggable external hook, not part of the open-source core.
5. **No SQLite cache tier yet**, by design (see `docs/technical-overview.md` §2-3, §9) — only
   add one once `resume`/`cadence` are demonstrably slow at real-world trail counts, not before.
6. **Claude Code project path decoding is lossy — mostly moot now.** Directory names encode `/`,
   `:`, and `.` all as `-`, so a project path containing any of those can't be perfectly
   reconstructed from the directory name alone. `read_metadata` now reads the real `cwd` directly
   off the transcript line when present (confirmed present on the large majority of real lines
   checked) and only falls back to the lossy decoder when it isn't — narrows this from "every
   session" to "the rare line missing `cwd`," but the decoder itself is still exactly as lossy as
   before for that fallback case.
7. **No adapters yet for Cursor, Gemini CLI, or other vendors.** The adapter interface
   (`src/trailant/adapters/base.py`) is meant to make this a self-contained addition — a new
   adapter module, a registry entry in `adapters/__init__.py`, and fixtures/tests mirroring the
   existing two.
8. **`trailant today`/`trailant week` don't actually summarize the day — they list it.** Each
   command filters the pre-built `trails.jsonl`/`marks.jsonl` down to the target date(s) and prints
   each session's already-extracted `ai_title` (a one-time heuristic pick made once at `reindex`
   time — Claude Code's own `"summary"` record if present, else the first non-wrapper user
   message). There's no day-level narrative rollup ("today you mostly worked on X, with a detour
   into Y") — just a per-session listing. Building one would be a new, optional step layered on top
   of `today`/`week`'s existing output, not a change to how `reindex` extracts `ai_title`.
9. **No way to leave a note addressed to a specific session.** `trailant log`/`close` already
   write marks, but nothing routes one *to* a particular session for its next resumption to see.
   The natural shape: extend `Mark` with an optional `to_session_id` field, and have `resume`/
   `status` surface any addressed-but-unread marks for a session when it comes up. Deliberately
   **not** live cross-session or cross-agent messaging — that's a different category of system
   (active coordination, not passive reconstruction) and arguably belongs to something like TRACE/
   OCTO rather than trailant, which never writes to vendor data and never sends anything without a
   human confirming first. This is an async mailbox, not a pipe: a note sits in `marks.jsonl` until
   the addressed session is next looked at through trailant, nothing more automatic than that.

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
