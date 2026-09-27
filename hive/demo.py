"""Offline DEMO: see the whole Hive loop work end-to-end with FAKE data, no network, no money.

  python -m hive demo            seeds <Hive>/hive_data_demo and serves the UI on :8791

Everything here is labeled DEMO and lives in its own data folder; your real hive_data, Queen DB
and wallet are never touched. Market data and the executor are replaced by in-process fakes.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .paths import FIB_DIR, HIVE_ROOT, TRADER_DIR

DEMO_DATA = HIVE_ROOT / "hive_data_demo"
DAY = 86400
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

# symbol, contract char, price, liquidity, confidence, rank, discovery, goplus
TOKENS = [
    ("DEMOHIGH", "1", 0.0420, 850_000, "high", "BUY", True, True),
    ("DEMOMED", "2", 0.0031, 240_000, "medium", "BUY", True, True),
    ("DEMOLOW", "3", 0.00077, 120_000, "low", "WATCH", True, True),
    ("DEMOTHIN", "4", 0.0150, 31_000, "medium", "BUY", True, True),     # thin liquidity -> approval
    ("DEMOTRAP", "5", 0.0090, 400_000, "high", "BUY", True, "honeypot"),  # honeypot -> rejected
    ("DEMOZONE", "6", 2.20, 2_000_000, None, "WATCH", False, True),     # zone-entry buy
    ("DEMOWATCH", "7", 6.10, 900_000, None, "BUY", False, True),        # watched, not in zone
]


def _addr(ch: str) -> str:
    return "0x" + ch * 40


def install_fakes():
    from hive import net
    import trader_bee.executor as ex

    by_addr = {_addr(ch): (sym, px, liq, gp) for sym, ch, px, liq, _, _, _, gp in TOKENS}

    def transport(url, headers, body, timeout):
        u = url.lower()
        if "dexscreener.com/latest/dex/tokens/" in u:
            c = u.rsplit("/", 1)[-1]
            if c not in by_addr:
                return 200, b'{"pairs":[]}'
            sym, px, liq, _ = by_addr[c]
            p = {"chainId": "base", "pairAddress": _addr("e"), "dexId": "demo-dex", "priceUsd": str(px), "priceNative": "0.0004",
                 "baseToken": {"address": c, "symbol": sym}, "quoteToken": {"address": USDC, "symbol": "USDC"},
                 "liquidity": {"usd": liq}, "volume": {"h24": liq / 4}, "pairCreatedAt": int((time.time() - 40 * DAY) * 1000),
                 "url": "https://dexscreener.com/base/demo"}
            return 200, json.dumps({"pairs": [p]}).encode()
        if "dexscreener.com/latest/dex/search" in u:
            return 200, b'{"pairs":[]}'
        if "gopluslabs" in u:
            c = u.rsplit("=", 1)[-1]
            gp = by_addr.get(c, (0, 0, 0, None))[3]
            if gp is None:
                return 200, b'{"result":{}}'
            return 200, json.dumps({"result": {c: {"is_honeypot": "1" if gp == "honeypot" else "0", "buy_tax": "0", "sell_tax": "0"}}}).encode()
        return 404, b"{}"

    def runner(cmd, p, timeout):
        if cmd == "quote":
            if p["src"].lower() == USDC:
                sym, px, liq, _ = by_addr[p["dst"].lower()]
                out = float(p["amount"]) / (px * 1.004)
                return {"ok": True, "winner": "kyber", "bestOut": out, "quotes": [{"venue": "kyber", "ok": True, "out": out}, {"venue": "1inch", "ok": True, "out": out * 0.997}]}
            sym, px, liq, _ = by_addr[p["src"].lower()]
            return {"ok": True, "winner": "1inch", "bestOut": float(p["amount"]) * px * 0.985}
        if cmd == "balances":
            return {"ok": True, "chain": p["chain"], "address": "0xDEMO000000000000000000000000000000000000", "native": 0.004,
                    "tokens": {USDC: {"amount": 187.5, "symbol": "USDC", "decimals": 6}}}
        if cmd == "address":
            return {"ok": True, "address": "0xDEMO000000000000000000000000000000000000"}
        return {"ok": False, "sent": False, "error": "DEMO executor never trades"}

    net.transport = transport
    net.MIN_INTERVAL_S = {}
    ex.runner = runner


def seed():
    from datetime import datetime, timezone

    from hive import bus
    from trader_bee.agent import TraderBee
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for sym, ch, px, liq, conf, rank, disc, gp in TOKENS:
        v = {"asset_id": f"base:{_addr(ch)}", "chain": "base", "contract": _addr(ch), "symbol": sym, "name": f"{sym} (demo)", "researched_at": now,
             "snapshot_id": "DEMO", "identity": {"status": "VERIFIED", "sources": ["dexscreener", "basescan", "geckoterminal"], "canonical_pool": _addr("e")},
             "gate": {"result": "PASS", "score": 21}, "rank": rank, "discovery": disc, "security": {"score": 88, "source": "demo"},
             "notes": "DEMO DATA — not a real token"}
        if conf:
            v["confidence"] = conf
        bus.publish("research.verdict", "research_agent", v)
    # Fib Bee reports DEMOZONE entering the buy zone (structure: ATL 1.0 -> body high 10)
    bus.publish("fib.zone.entered", "fib_agent", {
        "asset_id": f"base:{_addr('6')}", "chain": "base", "contract": _addr("6"), "symbol": "DEMOZONE", "structure_id": "FIB-DEMO01",
        "zone": "NDCAZ", "previous_zone": "REDLEG", "percent": 86.7, "price": 2.2, "in_buy_zone": True, "structure_status": "ACTIVE",
        "study_mode": "mature", "anchors": {"bottom": 1.0, "wick_high": 10.0, "body_high": 10.0}})
    fib_state = {"watchlist": {}, "assets": {}}
    for sym, ch, px, *_rest in TOKENS:
        if sym in ("DEMOZONE", "DEMOWATCH"):
            aid = f"base:{_addr(ch)}"
            fib_state["watchlist"][aid] = {"asset_id": aid, "chain": "base", "contract": _addr(ch), "symbol": sym, "rank": "WATCH" if sym == "DEMOZONE" else "BUY"}
            pct = (1 - (px - 1.0) / 9.0) * 100
            fib_state["assets"][aid] = {"status": "ACTIVE", "zone": "NDCAZ" if pct >= 82.6 else "NUK3", "percent": round(pct, 2), "in_buy_zone": pct >= 78.6,
                                        "price": px, "checked_at": now, "bottom": 1.0, "wick_high": 10.0, "body_high": 10.0}
    from .paths import sub
    (sub("fib_agent") / "state.json").write_text(json.dumps(fib_state, indent=1))
    queue = {}
    for sym, ch, liq, vol, b_, s_, age, sc in (("DEMOSCOUT", "8", 310_000, 420_000, 1210, 640, 52, 17.4), ("DEMONEW", "9", 88_000, 61_000, 380, 290, 30, 12.1)):
        aid = f"base:{_addr(ch)}"
        payload = {"asset_id": aid, "chain": "base", "contract": _addr(ch), "symbol": sym, "name": f"{sym} / WETH", "source": "discovery_scout/trending_pools",
                   "pool": _addr("e"), "observed": {"price_usd": 0.01, "liquidity_usd": liq, "volume_24h_usd": vol, "buys_24h": b_, "sells_24h": s_,
                                                     "change_24h_pct": 24.0, "pool_age_hours": age * 24},
                   "scout_score": sc, "reasons": ["trending pools on base", f"liq ${liq:,}", "DEMO DATA"], "requested_by": "discovery_scout"}
        bus.publish("research.request", "discovery_scout", payload)
        queue[aid] = {**payload, "status": "QUEUED", "first_seen": now, "last_seen": now, "requested_at": now, "times_seen": 1}
    (sub("scout") / "queue.json").write_text(json.dumps(queue, indent=1))
    bee = TraderBee()
    for _ in range(2):
        bee.tick()
    return bee


def main(port: int = 8791):
    os.environ["HIVE_DATA"] = str(DEMO_DATA)
    os.environ["QUEEN_DATA"] = str(DEMO_DATA / "queen")
    for p in (TRADER_DIR, FIB_DIR):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    fresh = not (DEMO_DATA / "bus" / "events.jsonl").exists()
    install_fakes()
    if fresh:
        bee = seed()
        from hive import queen_client
        for a in ("research_agent", "discovery_scout", "fib_agent", "market_direction", "bottom_blueprint_observatory"):
            queen_client.heartbeat(a, "healthy")
        print("DEMO seeded:", json.dumps(bee.status()["counts"]))
    from .ui.server import serve
    print("DEMO DATA ONLY — fake tokens, fake market, an executor that cannot trade.")
    serve(port)


if __name__ == "__main__":
    main()
