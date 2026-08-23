# 🐜 trailant

<p align="center">
  <img src="https://raw.githubusercontent.com/semanticintent/trailant/main/docs/assets/ant-trail-banner.png" alt="The Trail Ant — trailant's mascot, mid-stride, leaving a glowing trail behind" width="480">
</p>

Ants don't remember paths. They lay a trail as they move, and follow the strongest trail back.

`trailant` does the same for your work. It doesn't hold state of its own — it reads the trails
your tools already leave behind (Claude Code, Codex CLI, and other AI coding sessions) and
reconstructs where you were, so you can answer:

- **"Where was I?"** — resume the right session, in the right project, without hunting through
  directories or scrollback.
- **"What did I actually do today / this week?"** — a reconstructed activity view, useful for
  timesheets, standups, or just your own sanity.
- **"Am I pacing myself sustainably?"** — a cadence view of your own velocity over time, so a
  burnout trajectory shows up as data instead of only as hindsight.

No cloud, no telemetry, no account. Everything lives in plain, append-only JSONL files on your own
machine, so you can `cat` them, `grep` them, or check them into your own private git repo if you
want history on your history.

## Why not just use `claude --resume` / `codex resume`?

Those work fine within one vendor. `trailant` exists for the parts they don't cover: a single view
across *multiple* AI coding tools, a way to reconstruct what a session or day was actually about
after the fact, and a lightweight trend view over weeks — none of which any single vendor's CLI is
trying to solve.

## Design principles

1. **Transparent over opaque.** The source of truth is plain JSONL — the same format Claude Code
   and Codex already use for their own session logs. No database holds unique data.
2. **Cache, never store, derived state.** Any local index (e.g. SQLite) is a disposable
   accelerator, rebuildable at any time from the JSONL. Delete it whenever — nothing is lost.
3. **Supervised, not autonomous.** `trailant` never sends anything (a log, an email) without
   showing you the draft first. It's meant to make a human-in-the-loop workflow *faster*, not to
   replace the human in the loop.
4. **Vendor-agnostic via adapters.** Each AI coding tool gets a small adapter that normalizes its
   session format into one internal shape. Adding a new vendor is a self-contained addition.

See [`docs/technical-overview.md`](https://github.com/semanticintent/trailant/blob/main/docs/technical-overview.md) for the full design spec.

Mascot: [**the Trail Ant**](https://github.com/semanticintent/trailant/blob/main/docs/mascot.md) 🐜 — doesn't remember, just reads the trail.

## Install

```bash
git clone https://github.com/semanticintent/trailant.git
cd trailant
pip install -e .
```

## Quickstart

```bash
trailant reindex     # walk configured source directories, build the trail index
trailant resume       # list recent sessions across all vendors, ranked by recency
trailant today          # reconstructed view of today's activity
trailant log "debugging the retry logic in the ingest job"   # manual entry, no editor needed
trailant cadence          # velocity trend vs. your own baseline
trailant cadence --html   # same data as a static HTML report (also on `resume`)
```

Configuration lives at `~/.trailant/config.yaml` and is created with sane defaults on first run.
See `config.example.yaml` in this repo for the full set of options.

## Example output

`--html` on `resume`/`cadence` writes a static, screenshot-ready report instead of printing to
the terminal (`--output PATH` implies `--html`). These are real renders — synthetic demo data, but
the actual command output, not a mockup:

<p align="center">
  <img src="https://raw.githubusercontent.com/semanticintent/trailant/main/docs/assets/html-report-cadence.png" alt="trailant cadence --html — a 9-week bar chart of session counts" width="600">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/semanticintent/trailant/main/docs/assets/html-report-resume.png" alt="trailant resume --html — recent sessions across every vendor" width="600">
</p>

## Status

Early / pre-alpha. The Claude Code and Codex adapters are functional against the documented
session formats; other vendors are not yet implemented. Interfaces may change. Contributions and
adapters for other tools (Cursor, Gemini CLI, etc.) are very welcome — see
[`CONTRIBUTING.md`](https://github.com/semanticintent/trailant/blob/main/CONTRIBUTING.md).

## License

MIT — see [`LICENSE`](https://github.com/semanticintent/trailant/blob/main/LICENSE).
