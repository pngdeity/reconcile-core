"""Locate and load drumline profile configuration.

The JSON configs (manual entity merges, name resolutions, address map, and the
Google Groups routing files) carry real names and addresses, so they are kept
out of the repository. By default they are read from the repo-local, git-ignored
``var/drumline/`` directory; override with ``--config-dir`` or the
``RECONCILE_CORE_DRUMLINE_CONFIG`` environment variable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_DIR = REPO_ROOT / "var" / "drumline"

MERGE_FILES = {
    "merges": "manual_entity_merges.json",
    "resolutions": "manual_name_resolutions.json",
    "address_map": "manual_address_map.json",
    "invite_required": "group_invite_required.json",
    "blocked": "group_blocked.json",
    "hold": "group_hold.json",
}


def config_dir(path: Path | str | None = None) -> Path:
    """Resolve the config directory: explicit path, env var, else repo-local."""
    if path:
        return Path(path)
    env = os.environ.get("RECONCILE_CORE_DRUMLINE_CONFIG")
    return Path(env) if env else DEFAULT_CONFIG_DIR


def load(name: str, config: Path | str | None = None, default=None):
    """Load a JSON config file from the config dir, or ``default`` if absent."""
    path = config_dir(config) / name
    if not path.exists():
        return default
    return json.loads(path.read_text())


def merges(config: Path | str | None = None) -> list[dict]:
    return (load(MERGE_FILES["merges"], config, {}) or {}).get("merges", [])


def resolutions(config: Path | str | None = None) -> list[dict]:
    return (load(MERGE_FILES["resolutions"], config, {}) or {}).get("resolutions", [])


def address_map(config: Path | str | None = None) -> dict:
    return load(MERGE_FILES["address_map"], config, {}) or {}


def invite_required(config: Path | str | None = None) -> list[dict]:
    return (load(MERGE_FILES["invite_required"], config, {}) or {}).get(
        "invite_required", []
    )


def blocked(config: Path | str | None = None) -> list[dict]:
    return (load(MERGE_FILES["blocked"], config, {}) or {}).get("blocked", [])


def hold(config: Path | str | None = None) -> list[dict]:
    return (load(MERGE_FILES["hold"], config, {}) or {}).get("hold", [])
