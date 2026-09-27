import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
sys.path.insert(0, str(ROOT))

WETH = "0x4200000000000000000000000000000000000006"


def pool(tok, sym, liq=200_000, vol=150_000, age_h=72, buys=400, sells=300, chg=35, quote_first=False):
    created = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat()
    base, quote = (WETH, tok) if quote_first else (tok, WETH)
    name = f"WETH / {sym}" if quote_first else f"{sym} / WETH"
    return {"attributes": {"address": "0x" + "p" * 0 + tok[2:6] + "0" * 36, "name": name, "reserve_in_usd": str(liq),
                           "base_token_price_usd": "0.01" if not quote_first else "2500", "quote_token_price_usd": "2500" if not quote_first else "0.01",
                           "pool_created_at": created, "volume_usd": {"h24": str(vol)}, "transactions": {"h24": {"buys": buys, "sells": sells}},
                           "price_change_percentage": {"h24": str(chg)}},
            "relationships": {"base_token": {"data": {"id": f"base_{base}"}}, "quote_token": {"data": {"id": f"base_{quote}"}}}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_DATA", str(tmp_path / "hive"))
    monkeypatch.setenv("QUEEN_DATA", str(tmp_path / "queen"))
    monkeypatch.setenv("COINGECKO_API_KEY", "")
    from hive import net
    world = {"pools": []}

    def transport(url, h, b, t):
        if "/networks/base/" in url and "page=1" in url:
            return 200, json.dumps({"data": world["pools"]}).encode()
        return 200, b'{"data": []}'
    monkeypatch.setattr(net, "transport", transport)
    monkeypatch.setattr(net, "MIN_INTERVAL_S", {})
    net._cache.clear()
    return world


def test_filters_and_queue(env):
    import scout
    good, thin, young, dumpy = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40, "0x" + "4" * 40
    env["pools"] = [pool(good, "GOOD"), pool(thin, "THIN", liq=10_000), pool(young, "YOUNG", age_h=3), pool(dumpy, "DUMP", buys=100, sells=500),
                    pool("0x" + "5" * 40, "FLIP", quote_first=True)]
    s = scout.run_once()
    assert s["new"] == 2  # GOOD + FLIP (token on the quote side)
    q = scout.load_queue()
    assert set(q) == {f"base:{good}", "base:0x" + "5" * 40}
    assert q[f"base:{good}"]["symbol"] == "GOOD" and q["base:0x" + "5" * 40]["symbol"] == "FLIP"
    from hive import bus
    reqs = bus.tail(10, {"research.request"})
    assert len(reqs) == 2 and all(r["payload"]["requested_by"] == "discovery_scout" for r in reqs)
    assert not bus.tail(10, {"research.verdict"})  # the scout NEVER publishes verdicts


def test_no_duplicates_and_researched(env):
    import scout
    from hive import bus
    tok = "0x" + "1" * 40
    env["pools"] = [pool(tok, "GOOD")]
    scout.run_once()
    from hive import net
    net._cache.clear()
    assert scout.run_once()["new"] == 0
    bus.publish("research.verdict", "research_agent", {"asset_id": f"base:{tok}", "chain": "base", "contract": tok, "symbol": "GOOD",
                "researched_at": "2026-09-27T00:00:00Z", "identity": {"status": "VERIFIED", "sources": ["a", "b"]},
                "gate": {"result": "PASS"}, "rank": "WATCH", "discovery": True})
    net._cache.clear()
    scout.run_once()
    r = scout.load_queue()[f"base:{tok}"]
    assert r["status"] == "RESEARCHED" and r["verdict_rank"] == "WATCH"
    assert scout.queue_rows() == []


def test_same_ticker_flag_and_dismiss(env):
    import scout
    env["pools"] = [pool("0x" + "1" * 40, "VEX"), pool("0x" + "2" * 40, "VEX", liq=90_000)]
    scout.run_once()
    rows = scout.queue_rows()
    assert all(any("SAME TICKER" in x for x in r["reasons"]) for r in rows)
    assert scout.dismiss("vex", "decoys") == 2 and scout.queue_rows() == []


def test_source_down_reported(env, monkeypatch):
    import scout
    from hive import net
    monkeypatch.setattr(net, "transport", lambda *a: (503, b"down"))
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    s = scout.run_once()
    assert s["errors"] and s["new"] == 0
