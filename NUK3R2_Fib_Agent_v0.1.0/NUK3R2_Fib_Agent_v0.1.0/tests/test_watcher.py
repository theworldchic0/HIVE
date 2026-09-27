import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

TOKEN = "0x" + "b" * 40
POOL = "0x" + "c" * 40
QUOTE = "0x" + "d" * 40
DAY = 86400


@pytest.fixture
def hive_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_DATA", str(tmp_path / "hive"))
    monkeypatch.setenv("QUEEN_DATA", str(tmp_path / "queen"))
    monkeypatch.setenv("COINGECKO_API_KEY", "")
    from hive import net
    state = {"price": 5.0}
    closes = [5, 4, 3, 2, 1.0, 2, 4, 7, 10, 8, 6, 5, 5, 5, 5]
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        rows.append([1_700_000_000 + i * DAY, prev, max(prev, c), min(prev, c), c, 100])
        prev = c

    def transport(url, headers, body, timeout):
        if "/ohlcv/" in url:
            return 200, json.dumps({"data": {"attributes": {"ohlcv_list": rows[::-1]}}}).encode()
        if f"/pools/{POOL}" in url:
            return 200, json.dumps({"data": {"attributes": {"base_token_price_usd": str(state["price"]), "quote_token_price_usd": "1", "reserve_in_usd": "250000"},
                                             "relationships": {"base_token": {"data": {"id": f"base_{TOKEN}"}}, "quote_token": {"data": {"id": f"base_{QUOTE}"}}}}}).encode()
        return 404, b"{}"
    monkeypatch.setattr(net, "transport", transport)
    net._cache.clear()
    monkeypatch.setattr(net, "MIN_INTERVAL_S", {})
    return state


def verdict(rank="BUY", gate="PASS"):
    return {"asset_id": f"base:{TOKEN}", "chain": "base", "contract": TOKEN, "symbol": "BEE", "researched_at": "2026-09-27T00:00:00Z",
            "identity": {"status": "VERIFIED", "sources": ["dexscreener", "basescan"], "canonical_pool": POOL},
            "gate": {"result": gate, "score": 21}, "rank": rank}


def test_zone_entry_and_exit_events(hive_env):
    from hive import bus, net
    from src import watcher
    bus.publish("research.verdict", "research_agent", verdict())
    s = watcher.tick()
    assert s["watching"] == 1 and s["entered"] == 0  # price 5 = NUK3
    net._cache.clear()
    hive_env["price"] = 2.2  # (1 - 1.2/9) = 86.7% -> NDCAZ
    s = watcher.tick()
    assert s["entered"] == 1
    evs = bus.tail(10, {"fib.zone.entered"})
    assert evs[-1]["payload"]["in_buy_zone"] is True and evs[-1]["payload"]["zone"] == "NDCAZ"
    s = watcher.tick()
    assert s["entered"] == 0  # no duplicate while still inside
    net._cache.clear()
    hive_env["price"] = 6.0
    assert watcher.tick()["exited"] == 1


def test_failed_verdict_drops_from_watchlist(hive_env):
    from hive import bus
    from src import watcher
    bus.publish("research.verdict", "research_agent", verdict())
    watcher.tick()
    v = verdict(rank="AVOID")
    v["researched_at"] = "2026-09-28T00:00:00Z"
    bus.publish("research.verdict", "research_agent", v)
    assert watcher.tick()["watching"] == 0


def test_source_failure_is_data_error_not_silence(hive_env, monkeypatch):
    from hive import bus, net
    from src import watcher
    monkeypatch.setattr(net, "transport", lambda *a: (503, b"down"))
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    bus.publish("research.verdict", "research_agent", verdict())
    s = watcher.tick()
    assert s["errors"] == 1
    assert watcher.load_state()["assets"][f"base:{TOKEN}"]["status"] == "DATA_ERROR"
