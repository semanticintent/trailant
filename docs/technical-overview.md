# trailant — technical overview

> Ants don't remember paths. They lay a trail as they move, and follow the strongest trail back.
> `trailant` does the same for your work: it doesn't hold state — it reads the trails your tools
> already leave behind (AI coding sessions, git, email) and reconstructs where you were.

This document is the design spec for implementing `trailant` v0.1. It's written to be handed to
an agentic coding tool (e.g. Claude Code) as the starting brief for implementation, testing, and
open-source packaging.

---

## 1. Problem statement

Developers using multiple AI coding CLIs (Claude Code, Codex CLI, others) accumulate hundreds of
local session files with no unified way to answer:

- "Where was I?" — resuming across projects/tools without manually scanning directories
- "What did I actually do today/this week?" — reconstructing activity for timesheets, self-review
- "Am I pacing myself sustainably?" — velocity/cadence over time against your own baseline

Existing tools solve fragments of this (git activity digests, single-vendor session browsers,
generic journaling CLIs) but nothing unifies multiple AI coding tool vendors, git, and email into
one transparent, local-first, git-diffable store.

## 2. Design philosophy

1. **Transparent over opaque.** Source of truth is plain JSONL, not a database. Anyone can `cat`,
   `grep`, `git diff`, or hand-edit the data. This matches the native storage format both Claude
   Code and Codex already use for their own session logs — `trailant` extends an existing pattern
   rather than inventing a new one.
2. **Cache, never store, derived state.** Any database (SQLite or otherwise) is a disposable
   performance index, rebuildable at any time from the JSONL. It holds nothing unique. Deleting it
   is always safe.
3. **Supervised, not autonomous.** Nothing is sent (emails, logs) without a human glance first.
   This preserves the property that makes the underlying workflow predictable rather than brittle
   — see §8.
4. **Vendor-agnostic via adapters.** Each AI coding tool gets a thin adapter that normalizes its
   session format into one internal shape. Adding a new vendor means writing one adapter, not
   touching core logic.
5. **Local-first, no telemetry, no cloud sync required.** Everything lives under `~/.trailant/`.

## 3. Directory layout

```
~/.trailant/
├── config.yaml          # sources, self-log target, cadence thresholds
├── trails.jsonl          # append-only — one line per session (SOURCE OF TRUTH)
├── marks.jsonl            # append-only — one line per log/self-log entry (SOURCE OF TRUTH)
├── index.db               # derived SQLite cache — gitignored, rebuildable via `trailant reindex`
└── logs/
    └── 2026-08-22.md       # local self-log drafts held before send
```

## 4. Configuration

```yaml
# ~/.trailant/config.yaml
sources:
  claude_code:
    enabled: true
    root: ~/.claude/projects
  codex:
    enabled: true
    root: ~/.codex/sessions
  # future adapters register here: cursor, gemini-cli, etc.

self_log:
  send_to: you@yourmail.com
  send_via: null            # optional shell-out target, e.g. path to a local mail-send executable
  hold_before_send: true    # never auto-send; always show draft first

cadence:
  baseline_window_weeks: 12
  valley_flag_after_weeks: 8
```

## 5. Data model

### 5.1 `trails.jsonl` (one line per session)

```json
{
  "session_id": "db4961c3-...",
  "source": "claude_code",
  "project": "/Users/me/code/myapp",
  "started_at": "2026-08-22T09:14:00Z",
  "ended_at": "2026-08-22T11:02:00Z",
  "prompt_count": 34,
  "size_bytes": 128000,
  "file_path": "/home/me/.claude/projects/-Users-me-code-myapp/db4961c3-....jsonl",
  "file_mtime": 1755856920,
  "ai_title": "Refactor session-resume report parser"
}
```

### 5.2 `marks.jsonl` (one line per log entry)

```json
{
  "date": "2026-08-22",
  "kind": "session_close",
  "session_id": "db4961c3-...",
  "content": "Closed session on session-resume report parser. Fixed size calc bug, added ai_title extraction.",
  "sent_at": null
}
```

`kind` is one of: `session_close`, `self_log` (gap-day manual entry), `timesheet_day`.

### 5.3 `index.db` (derived — SQLite)

```sql
CREATE TABLE sessions (
  session_id   TEXT PRIMARY KEY,
  source       TEXT,
  project      TEXT,
  started_at   TEXT,
  ended_at     TEXT,
  prompt_count INTEGER,
  size_bytes   INTEGER,
  file_path    TEXT,
  file_mtime   INTEGER,
  ai_title     TEXT
);

CREATE TABLE marks (
  date         TEXT,
  kind         TEXT,
  session_id   TEXT,
  content      TEXT,
  sent_at      TEXT
);
```

Rebuilding: `trailant reindex` truncates and replays `trails.jsonl` + `marks.jsonl` in full. No
data lives in `index.db` that isn't derivable from the JSONL files. It should be gitignored.

## 6. Adapter interface

```
interface SourceAdapter:
    name() -> string                          # "claude_code" | "codex"
    root() -> path                             # resolved from config
    list_session_files() -> list[path]          # cheap fs walk, no parsing
    read_metadata(path) -> SessionMeta          # reads minimum bytes needed:
                                                  #   claude_code: first + last line of the jsonl
                                                  #   codex: just the session_meta header line
    read_full(path) -> Transcript                # full parse, called only on demand
                                                  #   (e.g. drafting a self-log summary)
```

### 6.1 Known vendor formats (as of Aug 2026)

**Claude Code** — `~/.claude/projects/<project-path-with-slashes-as-dashes>/<session-id>.jsonl`
One JSON object per line. Each line has `type`, `sessionId`, `uuid`, `parentUuid` (chains messages
into order). Sub-agent transcripts live in a sibling `<session-id>/subagents/` directory, each
with its own `.jsonl` + `.meta.json`.

**Codex CLI** — `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl`
First line is a `session_meta` object (id, cwd, model_provider). Remaining lines are
`response_item` objects with `role`/`content`, in file order (no uuid chaining). Sub-agent
sessions are separate files in the same date directory, distinguished by `source: "subagent"` in
their own `session_meta`. **Caveat:** Codex filters its own `/resume` list by `model_provider` —
adapter should read all sessions regardless of provider field, since the goal is a superset view,
not Codex's own filtered view. Some large/inactive sessions may be compressed to `.jsonl.zst` —
adapter should decompress transparently or skip with a warning.

Adapters should be written defensively: skip unparseable lines/files with a warning rather than
failing the whole index run — session files in the wild can be very large (some Codex rollouts
have been observed in the hundreds of MB to low GB range due to compaction history).

## 7. Index refresh algorithm

```
for each enabled source in config:
    adapter = get_adapter(source)
    for file in adapter.list_session_files():
        stat = fs.stat(file)
        cached = jsonl_index.lookup_by_path(file)   # in-memory map built from trails.jsonl
        if cached and cached.file_mtime == stat.mtime and cached.size_bytes == stat.size:
            continue   # unchanged — trust existing trail entry
        meta = adapter.read_metadata(file)
        trails_jsonl.upsert(meta)   # append new line, or rewrite file with corrected line
```

`stat()` across even tens of thousands of files is cheap; full re-parses only happen for
new/changed sessions. No SQLite involvement required for this step — it operates directly on the
JSONL append log, keeping the fast path fully transparent.

## 8. CLI command surface (v0.1 target)

```
trailant resume              # list sessions ranked by recency/project, output the resume command
trailant close [session_id]  # draft a session_close mark from the session transcript; show for
                               # review; write to marks.jsonl; hold-before-send per config
trailant log "note"          # instant manual mark, kind=self_log, no editor required
trailant today                 # reconstructed view of today: trails + marks; flags gap days
trailant week                  # timesheet-shaped rollup across the week
trailant cadence                # velocity trend vs baseline_window_weeks; flags valley-overdue
trailant status                  # quick "where was I" — last session, last mark, open threads
trailant reindex                  # rebuild index.db from trails.jsonl + marks.jsonl
```

No command should ever transmit data (email, external API) without an explicit confirmation step,
per the supervised-not-autonomous principle in §2.

## 9. Non-goals for v0.1

- No cloud sync or hosted service — local files only.
- No automatic sending of drafted logs — draft-and-hold only.
- No attempt to unify with vendor-native `/resume` — `trailant resume` prints the right resume
  invocation for the user to run, it doesn't wrap or replace vendor CLIs.
- Outlook/email integration is out of scope for the open-source core; it should be a pluggable
  hook (`self_log.send_via`) so Windows-only COM-interop code stays external to the core tool.

## 10. Suggested implementation order

1. Scaffolding: config loader, `~/.trailant/` bootstrap, JSONL read/append helpers.
2. Claude Code adapter (already prototyped once informally) + `trailant resume`.
3. Codex adapter, validated against real `~/.codex/sessions/` data.
4. `trailant log` / `trailant close` / `marks.jsonl`.
5. `trailant today` / `trailant week` reconstruction views.
6. `index.db` as an optional accelerator once query latency actually warrants it — not before.
7. `trailant cadence`.

## 11. Open-source packaging notes

- License: suggest MIT or Apache-2.0 (permissive, low friction for a small utility).
- README should lead with the ant/trail metaphor and a 10-second "what problem this solves"
  before any installation instructions.
- CLI binary name: `trailant` (or short alias `ant`).
- No telemetry, no network calls except vendor-agnostic self-update checks if added later —
  should be stated explicitly in the README given the personal/work-data nature of what it reads.
- Add a `.trailant.example/` fixture directory with fake session files for tests and for new
  contributors to try commands against without pointing at real data.

---

*This document is a design brief, not a finished spec — implementation details (language choice,
exact CLI framework, packaging) are left to whoever picks this up. The constraints that matter are
the ones in §2: transparent source of truth, disposable cache, supervised sending, vendor
adapters.*
