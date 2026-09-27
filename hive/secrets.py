"""API keys from local .env files. Values are returned to code, NEVER printed or logged.

Lookup order (first hit wins per key): process env → <HIVE_ROOT>/.env → module/.env (the
terminal's file, so keys you already set up for the trading terminal just work).
"""
from __future__ import annotations

import os
from pathlib import Path

from .paths import HIVE_ROOT, MODULE_DIR

PLACEHOLDER_MARKERS = ("PASTE_", "YOUR_", "REPLACE_ME", "<")


def _parse(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def get(name: str) -> str | None:
    v = os.environ.get(name)
    if not v:
        for f in (HIVE_ROOT / ".env", MODULE_DIR / ".env"):
            v = _parse(f).get(name)
            if v:
                break
    if not v or any(m in v for m in PLACEHOLDER_MARKERS):
        return None
    return v


def present(name: str) -> bool:
    return get(name) is not None
