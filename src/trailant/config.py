"""Config loading and first-run bootstrap for trailant.

Source of truth lives at ~/.trailant/config.yaml. This module is intentionally
small: it knows how to find the home dir, create defaults on first run, and
hand back a plain dict. No validation framework — keep it simple, keep it
readable, keep it easy for a new contributor to reason about end to end.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "sources": {
        "claude_code": {
            "enabled": True,
            "root": "~/.claude/projects",
        },
        "codex": {
            "enabled": True,
            "root": "~/.codex/sessions",
        },
    },
    "self_log": {
        "send_to": "",
        "send_via": None,
        "hold_before_send": True,
    },
    "cadence": {
        "baseline_window_weeks": 12,
        "valley_flag_after_weeks": 8,
    },
}


def trailant_home() -> Path:
    """The root directory for all trailant data. Override with TRAILANT_HOME for testing."""
    override = os.environ.get("TRAILANT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".trailant"


def config_path() -> Path:
    return trailant_home() / "config.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` onto `base`, keeping keys `override` doesn't
    mention. A plain dict.update() would let e.g. a config with only
    `sources: {codex: {...}}` silently wipe out the default `sources.claude_code`
    entry — this keeps partial edits partial."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    """Load config, creating a default one on first run. Never silently fails —
    if the file exists but is malformed, the error surfaces to the user."""
    home = trailant_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(exist_ok=True)

    path = config_path()
    if not path.exists():
        path.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False), encoding="utf-8")
        return DEFAULT_CONFIG

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Deep-merge over defaults so partially-written configs still work.
    return _deep_merge(DEFAULT_CONFIG, data)


def enabled_sources(config: dict[str, Any]) -> dict[str, Path]:
    """Return {source_name: resolved_root_path} for every enabled source."""
    out: dict[str, Path] = {}
    for name, cfg in config.get("sources", {}).items():
        if cfg.get("enabled"):
            out[name] = Path(cfg["root"]).expanduser()
    return out
