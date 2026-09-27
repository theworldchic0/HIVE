import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
sys.path.insert(0, str(ROOT))

A = "0x" + "a" * 40
B = "0x" + "b" * 40


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_DATA", str(tmp_path / "hive"))
    monkeypatch.setenv("QUEEN_DATA", str(tmp_path / "queen"))
    from hive import net
    w = {"px": {A: 1.0, B: 2.0}, "btc": 100000.0}

    def transport(url, h, b, t):
        if "BTC-USD/ticker" in url:
            return 200, json.dumps({"price": str(w["btc"])}).encode()
        if "dexscreener.com/latest/dex/tokens/" in url:
            a = url.rsplit("/", 1)[-1].lower()
            return 200, json.dumps({"pairs": [{"chainId": "base", "pairAddress": "0x" + "e" * 40, "priceUsd": str(w["px"][a]), "priceNative": "1",
                                               "baseToken": {"address": a, "symbol": "T"}, "quoteToken": {"address": "0x" + "f" * 40}, "liquidity": {"usd": 1e6}}]}).encode()
        return 404, b"{}"
    monkeypatch.setattr(net, "transport", transport)
    monkeypatch.setattr(net, "MIN_INTERVAL_S", {})
    net._cache.clear()
    return w


def v(addr, gate="PASS", rank="WATCH", at="2026-09-25T00:00:00Z", arch="Newborn Narrative"):
    return {"asset_id": f"base:{addr}", "chain": "base", "contract": addr, "symbol": "T" + addr[2], "researched_at": at,
            "identity": {"status": "VERIFIED", "sources": ["a", "b"]}, "gate": {"result": gate, "score": 20}, "rank": rank, "archetype": arch}


def test_cohort_freeze_observe_and_performance(world):
    import bottom_blueprint as bb
    import observatory as ob
    from hive import bus, net
    bus.publish("research.verdict", "research_agent", v(A))
    bus.publish("research.verdict", "research_agent", v(B, gate="FAIL", rank="FAIL"))
    r = ob.track(bb.clock)
    assert r["joined"] == 1  # only passers join
    c = ob.load_cohort()
    assert c[f"base:{A}"]["entry"]["price"] == 1.0 and c[f"base:{A}"]["clock_at_research"]["state"] == "BOTTOM_WINDOW_ACTIVE"
    # a re-research downgrades it: history grows, the frozen entry does not change
    bus.publish("research.verdict", "research_agent", v(A, rank="AVOID", at="2026-09-28T00:00:00Z"))
    world["px"][A] = 1.5
    world["btc"] = 110000.0
    net._cache.clear()
    ob.intake(bb.clock)
    ob.observe(force=True)
    m = ob.load_cohort()[f"base:{A}"]
    assert m["research"]["rank"] == "WATCH" and m["label_history"][-1]["rank"] == "AVOID"
    assert m["latest"]["token_return_pct"] == 50.0 and m["latest"]["btc_return_pct"] == 10.0 and m["latest"]["excess_pp"] == 40.0
    perf = ob.performance()
    assert perf["all"]["pct_beating_btc"] == 100.0 and perf["since_window_start"]["n"] == 1
    assert perf["by_archetype"]["Newborn Narrative"]["median_excess_pp"] == 40.0


def test_tracking_stops_at_boundary(world, monkeypatch):
    import bottom_blueprint as bb
    import observatory as ob
    from hive import bus
    from datetime import date
    bus.publish("research.verdict", "research_agent", v(A))
    ob.track(bb.clock)
    monkeypatch.setattr(ob, "end_date", lambda cfg: date(2020, 1, 1))
    assert ob.observe(force=True)["closed"] == 1
    assert ob.load_cohort()[f"base:{A}"]["status"] == "CLOSED"
