"""Manual market sell from the Trader Bee wallet (the beekeeper's per-trade action).

Preview by default. Only `--confirm GO` sends. The Bee itself never calls this.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from . import config, executor, policy


def manual_sell(bee, asset: str, pct: float, confirm: bool) -> int:
    cfg = bee.cfg
    mode = config.effective_mode(cfg)
    positions = bee.store.positions(mode)
    key = asset.lower()
    pos = next((p for p in positions if p["asset_id"] == key or p["symbol"].lower() == key), None)
    if not pos:
        print(f"No {mode} position for {asset}.")
        return 1
    if not 0 < pct <= 100:
        print("--pct must be in (0, 100]")
        return 1
    from hive import chains
    stable = chains.get(pos["chain"])["stable"]
    print(f"SELL {pct:g}% of {pos['symbol']} ({pos['chain']}) → {stable['symbol']}   mode={mode.upper()}")
    if mode == "paper":
        qty = pos["tokens_net"] * pct / 100
        q = executor.call("quote", {"chain": pos["chain"], "src": pos["contract"], "dst": stable["contract"], "amount": f"{qty:.12f}"})
        print(f"quote: ≈${float(q.get('bestOut') or 0):.2f} via {q.get('winner')}")
        if not confirm:
            print("PREVIEW ONLY — add --confirm GO to record the paper sell.")
            return 0
        bee.store.create_intent({"id": "TB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3),
                                 "idem_key": "sell:" + secrets.token_hex(8), "asset_id": pos["asset_id"], "chain": pos["chain"],
                                 "contract": pos["contract"], "symbol": pos["symbol"], "strategy": "manual_sell", "usd": float(q.get("bestOut") or 0),
                                 "mode": "paper", "state": "PAPER_FILLED", "token_amount": qty, "venue": q.get("winner")})
        print("PAPER SELL recorded.")
        return 0
    payload = {"chain": pos["chain"], "token": pos["contract"], "pct": pct, "slippagePct": policy.clamp_slippage(cfg),
               "allowedSpenders": cfg["execution"]["allowed_spenders"].get(pos["chain"], []), "approvalMode": cfg["execution"]["approval_mode"],
               "minGasNative": cfg["execution"]["min_gas_native"].get(pos["chain"], 0), "receiptTimeoutS": cfg["execution"]["receipt_timeout_s"],
               "retryOnce": cfg["execution"]["retry_once_on_revert"], "dryRun": not confirm}
    iid = "TB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    payload["intent_id"] = iid
    if confirm:
        bee.store.create_intent({"id": iid, "idem_key": "sell:" + iid, "asset_id": pos["asset_id"], "chain": pos["chain"], "contract": pos["contract"],
                                 "symbol": pos["symbol"], "strategy": "manual_sell", "mode": "live", "state": "SUBMITTING", "approved_by": "beekeeper"})
    r = executor.call("sell", payload, timeout=cfg["execution"]["receipt_timeout_s"] * 2 + 120)
    print(r.get("preview") or r)
    if not confirm:
        print("DRY RUN — nothing signed. Re-run with --confirm GO to sell.")
        return 0
    if r.get("ok"):
        bee.store.update_intent(iid, state="CONFIRMED", tx_hash=r.get("txHash"), venue=r.get("venue"), token_amount=r.get("tokensSold"),
                                usd=r.get("stableReceived"), result_json=r)
        print(f"SOLD. tx {r.get('txHash')}  received {r.get('stableReceived')} {stable['symbol']}")
        return 0
    bee.store.update_intent(iid, state="FAILED" if r.get("sent") else "REJECTED", reason=r.get("error"), result_json=r)
    print("SELL FAILED:", r.get("error"))
    return 1
