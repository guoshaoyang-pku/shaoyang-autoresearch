"""
Optional secrets loader for OSS releases.

Copy ``keys.example.json`` to ``keys.json`` at the repository root and fill in
values. ``keys.json`` is gitignored.

Modules should treat missing optional keys as empty; only user-facing
commands that truly need a secret should call ``require_keys_file``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_KEYS_NAME = "keys.json"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def keys_path() -> Path:
    return repo_root() / _KEYS_NAME


def load_keys() -> dict[str, Any] | None:
    """Return parsed keys.json, or None if missing/invalid."""
    p = keys_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def require_keys_file() -> dict[str, Any]:
    """Load keys.json or exit with a friendly message."""
    p = keys_path()
    if not p.exists():
        print(
            f"Missing {p.name}. Copy keys.example.json → {p.name} at repo root and fill secrets.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {p}: {e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"{p.name} must be a JSON object.", file=sys.stderr)
        sys.exit(2)
    return data


def get_semantic_scholar_api_key(keys: dict[str, Any] | None) -> str | None:
    if not keys:
        return None
    v = keys.get("semantic_scholar_api_key")
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        return None
    if "REPLACE" in v.upper():
        return None
    return v
