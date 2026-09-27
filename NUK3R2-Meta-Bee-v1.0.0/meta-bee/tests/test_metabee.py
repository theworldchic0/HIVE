import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
sys.path.insert(0, str(ROOT))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_DATA", str(tmp_path / "hive"))
    monkeypatch.setenv("QUEEN_DATA", str(tmp_path / "queen"))
    monkeypatch.setenv("COINGECKO_API_KEY", "")
    from hive import net
    w = {"down": set()}

    def transport(url, h, b, t):
        for d in w["down"]:
            if d in url:
                return 503, b"down"
        if "/coins/categories" in url:
            return 200, json.dumps([{"name": "AI Agents", "market_cap": 5e9, "market_cap_change_24h": 12.0, "volume_24h": 8e8},
                                    {"name": "Dog-Themed", "market_cap": 2e10, "market_cap_change_24h": -3.0, "volume_24h": 1e9}]).encode()
        if "/search/trending" in url:
            return 200, json.dumps({"coins": [{"item": {"id": "agentx", "name": "AgentX AI", "symbol": "AGX"}}, {"item": {"id": "zorbo", "name": "Zorbo", "symbol": "ZRB"}}],
                                    "categories": [{"name": "AI Agents"}]}).encode()
        if "trending_pools" in url:
            return 200, json.dumps({"data": [{"attributes": {"name": "MEOW / WETH", "address": "0x1", "volume_usd": {"h24": "1000"}}},
                                             {"attributes": {"name": "ZORBO / SOL", "address": "0x2", "volume_usd": {"h24": "5000"}}}]}).encode()
        if "token-boosts" in url:
            return 200, json.dumps([{"chainId": "solana", "tokenAddress": "abc", "description": "The first AI agent launchpad", "url": "https://dexscreener.com/solana/abc"}]).encode()
        if "token-profiles" in url:
            return 200, json.dumps([{"chainId": "base", "tokenAddress": "0x9", "description": "zorbo is the people's frog"}]).encode()
        if "api.llama.fi/protocols" in url:
            return 200, json.dumps([{"name": "Poly", "category": "Prediction Market", "tvl": 1e8, "change_7d": 25.0}]).encode()
        return 404, b"{}"
    monkeypatch.setattr(net, "transport", transport)
    monkeypatch.setattr(net, "MIN_INTERVAL_S", {})
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    net._cache.clear()
    return w


def test_once_classifies_every_source(world):
    import metabee
    out = metabee.once()
    assert all(r["ok"] for r in out["workers"]), out
    st = json.loads((Path(__import__("os").environ["HIVE_DATA"]) / "meta" / "state.json").read_text())
    by = {m["name"]: m for m in st["metas"]}
    ai = by["AI Agents"]
    assert ai["score_daily"] > 0 and ai["sources_24h"].get("cg_trending") and ai["sources_24h"].get("ds_boosts")
    assert by["Cat Memes"]["sources_24h"].get("gt_trending")
    assert by["Prediction Markets"]["capital"]["llama_tvl_change_7d"] == 25.0
    assert ai["curve_daily"] == "insufficient_data"  # honest until two full windows exist
    words = [e["word"] for e in st["emerging_unclassified"]]
    assert "zorbo" in words  # repeated across sources, matches no meta -> a candidate new meta


def test_one_broken_worker_does_not_stop_the_hunt(world):
    import metabee
    world["down"].add("api.llama.fi")
    out = metabee.once()
    bad = [r for r in out["workers"] if not r["ok"]]
    assert [r["worker"] for r in bad] == ["llama_categories"]
    assert any(r["ok"] for r in out["workers"])


def test_curve_labels():
    import metabee
    cfg = metabee.load_config()
    assert metabee.curve_label(2.0, 1.0, 0.5, cfg) == "accelerating"
    assert metabee.curve_label(2.0, 1.0, 1.0, cfg) == "rising"
    assert metabee.curve_label(1.0, 1.0, 1.0, cfg) == "flat"
    assert metabee.curve_label(0.4, 1.0, 1.0, cfg) == "declining"
    assert metabee.curve_label(0.8, 1.0, 1.0, cfg) == "fading"
    assert metabee.curve_label(1.0, 2.0, 1.0, cfg) == "peaking"
    assert metabee.curve_label(1.0, 0.0, 0.0, cfg) == "early_rising"
    assert metabee.curve_label(1.0, 0.0, 3.0, cfg) == "revival"
    assert metabee.curve_label(1.0, None, None, cfg) == "insufficient_data"


def test_rollup_with_history_publishes_shift(world):
    import metabee
    from hive import bus
    cfg = metabee.load_config()
    c = metabee.db()
    t = time.time()
    # 3 days of AI Agents history: quiet two days ago, busier yesterday, surging today
    for day, hits in ((3.2, 1), (2.5, 1), (1.5, 4), (0.5, 20)):
        for i in range(hits):
            metabee._obs(c, "cg_trending", "AI Agents", "trending_hit", 1, {"name": "x"}, ts=t - day * 86400 + i)
    (Path(__import__("os").environ["HIVE_DATA"]) / "meta" / "state.json").write_text(json.dumps({"metas": [{"name": "AI Agents", "curve_daily": "flat"}]}))
    st = metabee.rebuild(c, cfg)
    ai = next(m for m in st["metas"] if m["name"] == "AI Agents")
    assert ai["curve_daily"] == "accelerating"
    assert ai["curve_weekly"] == "insufficient_data"
    shifts = bus.tail(5, {"meta.shift"})
    assert shifts and shifts[-1]["payload"]["meta"] == "AI Agents" and shifts[-1]["payload"]["to"] == "accelerating"
