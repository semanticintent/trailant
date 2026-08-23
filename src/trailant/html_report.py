"""Static HTML report rendering for `--html` on a couple of commands.

Plain f-strings, no templating engine — matches the project's existing
"keep the dependency footprint minimal" pattern (see jsonl_store.py). The
point of this isn't a dashboard: it's letting trailant's own real output be
screenshotted/embedded somewhere (a README, a write-up, a demo) instead of
someone hand-mocking what the tool "would" show.
"""
from __future__ import annotations

import html as _html
from typing import Optional

from .utils import human_size

_STYLE = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 56px 48px;
    background: #0b0f14;
    color: #e8e6df;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }
  .header { display: flex; align-items: center; gap: 10px; margin-bottom: 28px; max-width: 720px; }
  .ant { font-size: 26px; }
  .brand { font-size: 20px; font-weight: 700; }
  .tag { color: #7fd8d0; font-size: 13px; margin-left: auto; letter-spacing: .03em; }
  .card { background: #11161d; border: 1px solid #1e2530; border-radius: 12px;
          padding: 32px; max-width: 720px; }
  .card h1 { font-size: 13px; color: #6b7480; font-weight: 600; margin: 0 0 20px;
             text-transform: uppercase; letter-spacing: .06em; }
  .session { padding: 14px 0; border-bottom: 1px solid #1e2530; }
  .session:last-child { border-bottom: none; }
  .source { color: #ff9d5c; font-weight: 600; font-size: 13px; }
  .title { color: #e8e6df; margin-top: 2px; }
  .meta { color: #6b7480; font-size: 12px; margin-top: 6px; }
  .bar-row { display: flex; align-items: center; gap: 12px; padding: 5px 0; }
  .bar-label { width: 82px; color: #6b7480; font-size: 12px; flex-shrink: 0; }
  .bar-track { flex: 1; background: #1e2530; border-radius: 4px; height: 10px; overflow: hidden; }
  .bar-fill { height: 100%; background: #7fd8d0; }
  .bar-count { width: 22px; text-align: right; color: #e8e6df; font-size: 12px; flex-shrink: 0; }
  .summary { margin-top: 18px; color: #9aa2ad; font-size: 13px; line-height: 1.6; }
  .footer { margin-top: 28px; max-width: 720px; }
  .badges { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
  .badge {
    display: inline-flex; align-items: center; gap: 9px;
    background: #11161d; border: 1px solid #2a3644; border-radius: 8px;
    padding: 11px 18px; color: #7fd8d0; font-size: 15px; font-weight: 700;
    letter-spacing: .01em; text-decoration: none;
  }
  .badge svg { width: 18px; height: 18px; flex-shrink: 0; fill: #7fd8d0; }
  .badge .emoji { font-size: 17px; line-height: 1; }
  .caption { color: #6b7480; font-size: 12px; }
"""

_GITHUB_ICON = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258'
    '.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.385-1.333'
    '-1.755-1.333-1.755-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07'
    ' 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466'
    '-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23'
    '.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23'
    '.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92'
    '.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092'
    ' 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>'
)


def _shell(title: str, tag: str, body: str, caption: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>trailant — {_html.escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
  <div class="header">
    <span class="ant">\U0001F41C</span><span class="brand">trailant</span>
    <span class="tag">{_html.escape(tag)}</span>
  </div>
  <div class="card">
    <h1>{_html.escape(title)}</h1>
    {body}
  </div>
  <div class="footer">
    <div class="badges">
      <span class="badge">{_GITHUB_ICON}github.com/semanticintent/trailant</span>
      <span class="badge"><span class="emoji">\U0001F4E6</span>pip install trailant</span>
    </div>
    <div class="caption">{_html.escape(caption)}</div>
  </div>
</body>
</html>
"""


def render_resume_html(trails: list[dict]) -> str:
    rows = []
    for s in trails:
        title = s.get("ai_title") or "(untitled)"
        source = _html.escape(s.get("source", ""))
        project = _html.escape(s.get("project") or "")
        size = _html.escape(human_size(s.get("size_bytes", 0)))
        rows.append(
            f'\n    <div class="session">'
            f'\n      <div class="source">[{source}]</div>'
            f'\n      <div class="title">{_html.escape(title)}</div>'
            f'\n      <div class="meta">{project} · {s.get("prompt_count", 0)} prompts · {size}</div>'
            f'\n    </div>'
        )
    body = "\n".join(rows) if rows else '<div class="summary">No sessions indexed yet.</div>'
    return _shell(
        title="resume — recent sessions across every vendor",
        tag="local-first · no cloud",
        body=body,
        caption="Generated by `trailant resume --html` — reconstructed from local "
                "session trails, nothing sent anywhere.",
    )


def render_cadence_html(weeks_sorted: list[str], counts: dict, avg: float,
                         valley_note: Optional[str]) -> str:
    max_count = max((counts[w] for w in weeks_sorted), default=1) or 1
    rows = []
    for w in weeks_sorted:
        c = counts[w]
        pct = round(c / max_count * 100)
        rows.append(
            f'\n    <div class="bar-row">'
            f'\n      <div class="bar-label">{_html.escape(w)}</div>'
            f'\n      <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>'
            f'\n      <div class="bar-count">{c}</div>'
            f'\n    </div>'
        )
    note = _html.escape(valley_note) if valley_note else "No valley currently flagged in this window."
    body = "\n".join(rows) + f'\n    <div class="summary">Average: {avg:.1f} sessions/week<br>{note}</div>'
    return _shell(
        title=f"cadence — last {len(weeks_sorted)} weeks",
        tag="your own baseline, not anyone else's",
        body=body,
        caption="Generated by `trailant cadence --html` — reconstructed from local "
                "session trails, nothing sent anywhere.",
    )
