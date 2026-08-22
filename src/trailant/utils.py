from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def best_effort_date(session: dict) -> str:
    """Return a YYYY-MM-DD string for a trail record, preferring started_at,
    falling back to file_mtime. Sessions are noisy — timestamps aren't always
    present in every vendor's metadata line, so this never raises."""
    started = session.get("started_at")
    if started:
        try:
            return started[:10]
        except Exception:
            pass
    mtime = session.get("file_mtime")
    if mtime:
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    return "unknown"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TB"


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def iso_week(date_str: str) -> Optional[str]:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"
