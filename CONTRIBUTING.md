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

## Findings from a second independent Windows validation (against 0.5.1)

Verified where noted below; the rest are plausible and well-evidenced but unverified locally (no
Windows box to hand). Roughly ordered by value ÷ how confidently it can be fixed without one.

10. **`--html` output drops the secret warning the terminal shows — the most important item here.**
    Confirmed directly: `render_resume_html` in `html_report.py` never references `secret_hits` at
    all. A session flagged `🔒 possible secret detected (Nx)` in the terminal shows nothing in the
    HTML — and HTML is the artifact that actually leaves the machine (emailed, committed, attached
    to a ticket), the opposite of where a warning like this can afford to go missing. Fix: render
    the same indicator per session in `render_resume_html`, and add a report-level banner when any
    included session is flagged. Consider also defaulting `--output`'s target directory to
    `~/.trailant/reports/` rather than the current working directory, since two generated reports
    already ended up inside a project directory during this validation.
11. **Codex SQL-sourced titles skip the truncation the JSONL-fallback path already has.** Found
    while fixing #10, not reported externally. In `adapters/codex.py`'s SQL-enrichment block,
    `sql_title` (`name`/`title`/`first_user_message` from the `threads` row) is used as-is, but the
    JSONL-derived `first_prompt_title` fallback is truncated to 80 chars. Since Codex's own `title`
    column is frequently just the raw first message (not a real summary), an untruncated SQL title
    can occupy several terminal/HTML lines. Apply the same truncation to `sql_title` before it
    becomes the final `ai_title` candidate.
12. **`resume --print-command` emits a bash-only `cd X && Y`**, which is a parse error on Windows
    PowerShell 5.1 (`&&`/`||` chaining arrived in PowerShell 7). Fix needs no OS detection: print
    the `cd`/resume command as two separate lines instead of one chained line — valid in every
    shell, including POSIX ones, and each line stays independently copy-pasteable.
13. **Codex-enriched `project`/`cwd` values may carry a Windows extended-length `\\?\` prefix**
    (e.g. `\\?\C:\Projects`), inherited from `Path.resolve()` in the SQL-lookup fallback and/or
    however Codex itself wrote the `cwd` column. Same directory can then render two different ways
    across rows. Strip a leading `\\?\` (and `\\?\UNC\` → `\\`) at the point metadata is read, not
    at display time, so every consumer (terminal, `--html`, future `--project` filters) sees the
    normalized form. Unverified locally — no Windows box to confirm the exact prefix shape against.
14. **`trailant diff`'s snapshot doesn't track per-session state, only session-id-set/counts/marks.**
    A session that's actively being worked on (more prompts, a title change, an archive flip) but
    was already known produces no signal at all — `diff` only notices sessions appearing/
    disappearing and per-source pool-size shifts. Recommended per-session snapshot fields:
    `ended_at`, `prompt_count`, a hash of `title`/`project` (not the raw text, to avoid duplicating
    anything `secrets.enabled` would otherwise flag, into a file this tool itself writes) — surfaced
    as e.g. `1 session resumed`, `3 prompts added`, `1 title updated`.
15. **`--html` output has no coverage or index-freshness line.** `status`'s terminal output has had
    one since Phase 3 (`Index: refreshed ... — claude_code: N sessions, ...`); `render_resume_html`/
    `render_cadence_html` never got the equivalent. Without it, a stale saved report and a genuinely
    quiet week look identical to whoever's reading the HTML later — the same "unknown vs. zero"
    problem status already solved, just not carried into this sink.
16. **`resume`/`today` display fields don't match what they sort/filter by, and can read as
    confusing rather than wrong.** `resume` sorts by last activity (correct, per Phase 2) but shows
    each session's *start* timestamp as the primary field — a March session can legitimately outrank
    an August one and look unsorted until you check `started_at` vs the actual order. `today`'s
    parenthesized prompt count is the session's *lifetime* total, not prompts specifically from
    today, which can read as "8,000 prompts happened today" for a long-running resumed session.
    Recommended labels: `active <date> · started <date>` for `resume`; keep the lifetime count in
    `today` but caption it explicitly as lifetime rather than implying it's today's count, since a
    true per-day count isn't available without richer per-turn data than `SessionMeta` currently
    stores.

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
