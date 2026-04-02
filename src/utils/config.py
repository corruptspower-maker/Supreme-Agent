"""Configuration loader: merges YAML files and .env overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env once at import time; silent if absent
load_dotenv(dotenv_path=Path(__file__).parents[2] / ".env", override=False)

_CONFIG_DIR = Path(__file__).parents[2] / "config"

_KNOWN_CONFIGS = [
    "agent",
    "models",
    "tools",
    "memory",
    "safety",
    "escalation",
    "ui",
    "mcp",
]


def load_config(name: str) -> dict[str, Any]:
    """Load and return a single config YAML by name (without extension).

    Args:
        name: Filename stem, e.g. ``"agent"`` loads ``config/agent.yaml``.

    Returns:
        Parsed YAML content as a plain dict.

    Raises:
        FileNotFoundError: If the requested config file does not exist.
        ValueError: If the YAML file cannot be parsed.
    """
    path = _CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse {path}: {exc}") from exc
    return data if data is not None else {}


def get_full_config() -> dict[str, Any]:
    """Merge all known YAML configs into a single dict.

    Each top-level YAML key is preserved as-is.  When two files share a
    top-level key, the later file wins.

    Environment variables named ``EA_<SECTION>__<KEY>`` (double underscore as
    separator) override scalar leaf values inside the merged config:

        EA_AGENT__NAME="My Agent"  →  config["agent"]["name"] = "My Agent"

    Returns:
        Merged configuration dict.
    """
    merged: dict[str, Any] = {}
    for name in _KNOWN_CONFIGS:
        path = _CONFIG_DIR / f"{name}.yaml"
        if path.exists():
            merged.update(load_config(name))

    _apply_env_overrides(merged)
    return merged


def _apply_env_overrides(config: dict[str, Any]) -> None:
    """Mutate *config* in-place with ``EA_``-prefixed environment variables.

    Convention: ``EA_SECTION__KEY=value`` sets ``config[section][key] = value``.
    Only two-level paths are supported; deeper nesting is not auto-resolved.
    """
    prefix = "EA_"
    for key, raw_value in os.environ.items():
        if not key.startswith(prefix):
            continue
        stripped = key[len(prefix):]
        if "__" not in stripped:
            continue
        section, field = stripped.split("__", 1)
        section = section.lower()
        field = field.lower()
        if section in config and isinstance(config[section], dict):
            config[section][field] = _coerce(raw_value)


def _coerce(value: str) -> bool | int | float | str:
    """Coerce a string env-var value to an appropriate scalar type."""
    if value.lower() in {"true", "yes", "1"}:
        return True
    if value.lower() in {"false", "no", "0"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value
