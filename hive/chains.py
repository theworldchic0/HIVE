"""Chain registry shared by the Hive. Mirrors module/config.json (the terminal's source of truth)
when it is present so the two halves can never disagree about RPCs or dollar stables."""
from __future__ import annotations

import json

from .paths import MODULE_DIR

# Protocol constants. The dollar-true stables are the same verified contracts the terminal ships.
CHAINS = {
    "base": {
        "chain_id": 8453, "gt_network": "base", "dexscreener": "base", "kyber_slug": "base",
        "rpc": "https://mainnet.base.org", "explorer": "https://basescan.org", "tradable": True, "evm": True,
        "cg_platform": "base", "blockscout": "https://base.blockscout.com/api/v2",
        "stable": {"symbol": "USDC", "contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "decimals": 6},
    },
    "robinhood": {
        "chain_id": 4663, "gt_network": "robinhood", "dexscreener": "robinhood", "kyber_slug": "robinhood",
        "rpc": "https://rpc.mainnet.chain.robinhood.com", "explorer": None,  # not yet verified — links are shown only when known
        "tradable": True, "evm": True, "cg_platform": None, "blockscout": None,
        "stable": {"symbol": "USDG", "contract": "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168", "decimals": 6},
    },
    # WATCH-ONLY chains: research, the Scout, the Meta Bee and the Fib Bee can read them; nothing trades them.
    "solana": {"chain_id": None, "gt_network": "solana", "dexscreener": "solana", "tradable": False, "evm": False,
               "cg_platform": "solana", "blockscout": None, "explorer": "https://solscan.io"},
    "ethereum": {"chain_id": 1, "gt_network": "eth", "dexscreener": "ethereum", "tradable": False, "evm": True,
                 "cg_platform": "ethereum", "blockscout": "https://eth.blockscout.com/api/v2", "explorer": "https://etherscan.io"},
    "arbitrum": {"chain_id": 42161, "gt_network": "arbitrum", "dexscreener": "arbitrum", "tradable": False, "evm": True,
                 "cg_platform": "arbitrum-one", "blockscout": "https://arbitrum.blockscout.com/api/v2", "explorer": "https://arbiscan.io"},
    "bsc": {"chain_id": 56, "gt_network": "bsc", "dexscreener": "bsc", "tradable": False, "evm": True,
            "cg_platform": "binance-smart-chain", "blockscout": None, "explorer": "https://bscscan.com"},
}


def by_dexscreener(ds_chain: str) -> str | None:
    for k, v in CHAINS.items():
        if v.get("dexscreener") == (ds_chain or "").lower():
            return k
    return None


def by_cg_platform(platform: str) -> str | None:
    for k, v in CHAINS.items():
        if v.get("cg_platform") and v["cg_platform"] == platform:
            return k
    return None


def norm_contract(chain: str, contract: str) -> str:
    """EVM addresses are case-insensitive (lowercase); Solana base58 is case-SENSITIVE (kept as-is)."""
    c = get(chain)
    return contract.lower() if (c is None or c.get("evm", True)) and contract.startswith("0x") else contract


def asset_id(chain: str, contract: str) -> str:
    return f"{chain.lower()}:{norm_contract(chain, contract)}"


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
