"""Config + arming. The config file is the beekeeper's; the Bee reads it every tick and never writes it."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "trader_bee.json"
SECRETS = ROOT / "secrets"
KEY_FILE = SECRETS / "agent_wallet.key"
ARM_FILE = SECRETS / "ARMED"


def load(path: Path | None = None) -> dict:
    return json.loads((path or CONFIG_FILE).read_text(encoding="utf-8"))


def armed() -> dict | None:
    """The arm record, or None. Arming is a file the human creates via `trader.py arm`."""
    if not ARM_FILE.exists():
        return None
    try:
        rec = json.loads(ARM_FILE.read_text(encoding="utf-8"))
    except Exception:
        rec = None
    return rec if isinstance(rec, dict) else {"armed": True, "note": "arm file unreadable — still treated as ARMED; run disarm to stop"}


def effective_mode(cfg: dict) -> str:
    return "live" if cfg.get("mode") == "live" and armed() is not None and KEY_FILE.exists() else "paper"
