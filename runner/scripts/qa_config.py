"""Locate and load the project's QA config (.qa/qa.config.yaml).

Search order: $QA_CONFIG, then .qa/qa.config.yaml in the cwd or any parent.
The project root is the directory that holds the .qa folder; relative paths
in the config (env_file, scratch, ...) resolve against it.

A git-ignored .qa/qa.config.local.yaml next to it, when present, is merged on
top (nested keys override one by one). It holds what differs per checkout, for
example the dev-server URL of a git worktree that runs on its own port.
"""
from __future__ import annotations

import os
import pathlib
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is missing: pip install pyyaml (or use ~/.claude/skills/.venv/bin/python3)")

CONFIG_NAME = "qa.config.yaml"
LOCAL_NAME = "qa.config.local.yaml"


def find_config(start: pathlib.Path | None = None) -> pathlib.Path:
    env = os.environ.get("QA_CONFIG")
    if env:
        path = pathlib.Path(env).expanduser().resolve()
        if path.is_file():
            return path
        sys.exit(f"QA_CONFIG points to a missing file: {env}")
    here = (start or pathlib.Path.cwd()).resolve()
    for folder in [here, *here.parents]:
        candidate = folder / ".qa" / CONFIG_NAME
        if candidate.is_file():
            return candidate
    sys.exit("no .qa/qa.config.yaml found from here upward. Run the qa-agent-setup skill first.")


def merge(base: dict, override: dict) -> dict:
    """Deep-merge override into a copy of base: dicts merge key by key, anything else replaces."""
    out = dict(base)
    for key, value in override.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load(path: pathlib.Path | None = None) -> tuple[dict, pathlib.Path]:
    """Return (config, project_root), with qa.config.local.yaml merged on top when it exists."""
    config_path = path or find_config()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    local = config_path.parent / LOCAL_NAME
    if local.is_file():
        cfg = merge(cfg, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    return cfg, config_path.parent.parent


def load_env_file(path: pathlib.Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding what is already set. Never prints values."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def resolve_secret(auth: dict, root: pathlib.Path) -> str | None:
    """Read the secret named by auth.env_var, loading auth.env_file first if needed. Returns None when missing."""
    var = auth.get("env_var")
    if not var:
        return None
    if not os.environ.get(var) and auth.get("env_file"):
        load_env_file(root / auth["env_file"])
    return os.environ.get(var)
