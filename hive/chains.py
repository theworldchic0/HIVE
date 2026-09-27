"""Chain registry shared by the Hive. Mirrors module/config.json (the terminal's source of truth)
when it is present so the two halves can never disagree about RPCs or dollar stables."""
from __future__ import annotations

import json

from .paths import MODULE_DIR

# Protocol constants. The dollar-true stables are the same verified contracts the terminal ships.
CHAINS = {
    "base": {
        "chain_id": 8453, "gt_network": "base", "dexscreener": "base", "kyber_slug": "base",
        "rpc": "https://mainnet.base.org", "explorer": "https://basescan.org",
        "stable": {"symbol": "USDC", "contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "decimals": 6},
    },
    "robinhood": {
        "chain_id": 4663, "gt_network": "robinhood", "dexscreener": "robinhood", "kyber_slug": "robinhood",
        "rpc": "https://rpc.mainnet.chain.robinhood.com", "explorer": None,  # not yet verified — links are shown only when known
        "stable": {"symbol": "USDG", "contract": "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168", "decimals": 6},
    },
}


def _merge_module_config():
    try:
        cfg = json.loads((MODULE_DIR / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return
    for key, c in (cfg.get("chains") or {}).items():
        if key in CHAINS:
            CHAINS[key]["rpc"] = c.get("rpc") or CHAINS[key]["rpc"]
            CHAINS[key]["gt_network"] = c.get("gtNetwork") or CHAINS[key]["gt_network"]
            CHAINS[key]["kyber_slug"] = c.get("kyberSlug") or CHAINS[key]["kyber_slug"]


_merge_module_config()


def get(chain: str) -> dict | None:
    return CHAINS.get((chain or "").lower())


def by_id(chain_id: int) -> tuple[str, dict] | None:
    for k, v in CHAINS.items():
        if v["chain_id"] == chain_id:
            return k, v
    return None
