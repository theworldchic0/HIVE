import json
import sys
from pathlib import Path

import pytest

BEE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BEE.parents[1]))
sys.path.insert(0, str(BEE))

STABLE_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def addr(ch: str) -> str:
    return "0x" + ch * 40


class Market:
    """Fake DexScreener / GoPlus world. Tokens: contract(lower) -> dict(price, liq, age_h, goplus, clones)."""

    def __init__(self):
        self.tokens = {}
        self.down = False

    def add(self, contract, price=0.01, liq=500_000, age_h=24 * 30, goplus="clean", symbol="BEE"):
        self.tokens[contract.lower()] = {"price": price, "liq": liq, "age_h": age_h, "goplus": goplus, "symbol": symbol, "clones": []}

    def transport(self, url, headers, body, timeout):
        import time
        if self.down:
            return 503, b"down"
        if "dexscreener.com/latest/dex/tokens/" in url:
            c = url.rsplit("/", 1)[-1].lower()
            t = self.tokens.get(c)
            if not t:
                return 200, b'{"pairs": []}'
            created = int((time.time() - t["age_h"] * 3600) * 1000)
            pair = {"chainId": "base", "pairAddress": addr("e"), "dexId": "uniswap", "priceUsd": str(t["price"]), "priceNative": "0.000004",
                    "baseToken": {"address": c, "symbol": t["symbol"]}, "quoteToken": {"address": STABLE_BASE.lower(), "symbol": "USDC"},
                    "liquidity": {"usd": t["liq"]}, "volume": {"h24": 1000}, "pairCreatedAt": created, "url": "https://dexscreener.com/base/x"}
            return 200, json.dumps({"pairs": [pair]}).encode()
        if "dexscreener.com/latest/dex/search" in url:
            pairs = []
            for c, t in self.tokens.items():
                for cl in t["clones"]:
                    pairs.append({"chainId": "base", "baseToken": {"address": cl["contract"], "symbol": t["symbol"]}, "liquidity": {"usd": cl["liq"]}})
            return 200, json.dumps({"pairs": pairs}).encode()
        if "gopluslabs" in url:
            c = url.rsplit("=", 1)[-1].lower()
            t = self.tokens.get(c)
            if not t or t["goplus"] is None:
                return 200, b'{"result": {}}'
            flags = {"is_honeypot": "1" if t["goplus"] == "honeypot" else "0", "buy_tax": "0.01", "sell_tax": "0.2" if t["goplus"] == "taxed" else "0.01"}
            return 200, json.dumps({"result": {c: flags}}).encode()
        return 404, b"{}"


class FakeExecutor:
    def __init__(self, market):
        self.m = market
        self.calls = []
        self.buy_result = None  # override dict for buy
        self.roundtrip = 0.98
        self.impact = 0.005
        self.stable = 1000.0
        self.native = 0.01
        self.receipt = {"ok": True, "status": 1, "tokensReceived": 123.0}

    def __call__(self, cmd, payload, timeout):
        self.calls.append((cmd, payload))
        if cmd == "quote":
            if payload["src"].lower() == STABLE_BASE.lower():
                t = self.m.tokens[payload["dst"].lower()]
                out = float(payload["amount"]) / (t["price"] * (1 + self.impact))
                return {"ok": True, "winner": "kyber", "bestOut": out, "quotes": [{"venue": "kyber", "ok": True, "out": out}]}
            t = self.m.tokens[payload["src"].lower()]
            return {"ok": True, "winner": "1inch", "bestOut": float(payload["amount"]) * t["price"] * self.roundtrip}
        if cmd == "balances":
            return {"ok": True, "address": addr("a"), "native": self.native, "tokens": {STABLE_BASE.lower(): {"amount": self.stable}}}
        if cmd == "buy":
            if self.buy_result is not None:
                return self.buy_result
            t = self.m.tokens[payload["token"].lower()]
            return {"ok": True, "sent": True, "txHash": "0x" + "f" * 64, "venue": "kyber", "tokensReceived": payload["usd"] / t["price"], "stableSpent": payload["usd"]}
        if cmd == "receipt":
            return self.receipt
        if cmd == "limit-sell":
            return {"ok": True, "orderHash": "0xorder"}
        if cmd == "address":
            return {"ok": True, "address": addr("a")}
        raise AssertionError(f"unexpected executor command {cmd}")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_DATA", str(tmp_path / "hive"))
    monkeypatch.setenv("QUEEN_DATA", str(tmp_path / "queen"))
    monkeypatch.setenv("COINGECKO_API_KEY", "")
    from hive import net
    from trader_bee import config, executor
    m = Market()
    fx = FakeExecutor(m)
    monkeypatch.setattr(net, "transport", m.transport)
    monkeypatch.setattr(net, "MIN_INTERVAL_S", {})
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    net._cache.clear()
    monkeypatch.setattr(executor, "runner", fx)
    sec = tmp_path / "secrets"
    sec.mkdir()
    monkeypatch.setattr(config, "SECRETS", sec)
    monkeypatch.setattr(config, "KEY_FILE", sec / "agent_wallet.key")
    monkeypatch.setattr(config, "ARM_FILE", sec / "ARMED")
    cfg = config.load()
    from trader_bee.agent import TraderBee
    from trader_bee.store import Store
    bee = TraderBee(Store(tmp_path / "bee.db"), cfg)

    class W:
        pass
    w = W()
    w.m, w.fx, w.bee, w.cfg, w.net = m, fx, bee, cfg, net
    w.arm = lambda: (config.KEY_FILE.write_text("0x" + "1" * 64), config.ARM_FILE.write_text("{}"), cfg.__setitem__("mode", "live"))
    return w


def verdict(contract, rank="BUY", gate="PASS", confidence="high", discovery=True, sources=("dexscreener", "basescan"), researched_at=None,
            security=85, chain="base", symbol="BEE", scores=None, **extra):
    from datetime import datetime, timezone
    v = {"asset_id": f"{chain}:{contract.lower()}", "chain": chain, "contract": contract, "symbol": symbol,
         "researched_at": researched_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
         "identity": {"status": "VERIFIED", "sources": list(sources), "canonical_pool": addr("e")},
         "gate": {"result": gate, "score": 20}, "rank": rank, "discovery": discovery,
         "security": {"score": security, "source": "research"} if security is not None else None}
    if confidence:
        v["confidence"] = confidence
    if scores:
        v["scores"] = scores
    v.update(extra)
    return v


def zone_event(contract, structure="FIB-1", price=0.01, symbol="BEE", bottom=0.009, body_high=0.03, wick_high=0.032):
    return {"asset_id": f"base:{contract.lower()}", "chain": "base", "contract": contract, "symbol": symbol, "structure_id": structure,
            "zone": "NDCAZ", "previous_zone": "REDLEG", "percent": 95.0, "price": price, "in_buy_zone": True, "structure_status": "ACTIVE",
            "study_mode": "mature", "anchors": {"bottom": bottom, "wick_high": wick_high, "body_high": body_high}}
