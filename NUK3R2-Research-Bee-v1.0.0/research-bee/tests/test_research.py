import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
sys.path.insert(0, str(ROOT))

REAL = "0x" + "a" * 40
DECOY = "0x" + "b" * 40
POOL = "0x" + "c" * 40
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def pair(addr, liq, chain="base"):
    return {"chainId": chain, "pairAddress": POOL if addr == REAL else "0x" + "d" * 40, "dexId": "aerodrome", "priceUsd": "0.5", "priceNative": "0.0002",
            "baseToken": {"address": addr, "symbol": "BEE", "name": "Bee Protocol"}, "quoteToken": {"address": USDC, "symbol": "USDC"},
            "liquidity": {"usd": liq}, "volume": {"h24": liq / 3}, "pairCreatedAt": int((time.time() - 1000 * 86400) * 1000), "url": "https://dexscreener.com/base/x"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_DATA", str(tmp_path / "hive"))
    monkeypatch.setenv("QUEEN_DATA", str(tmp_path / "queen"))
    monkeypatch.setenv("COINGECKO_API_KEY", "")
    from hive import net
    w = {"cg_platform_contract": REAL, "site_has_contract": True, "down": set()}

    def transport(url, headers, body, timeout):
        host = url.split("/")[2]
        if host in w["down"]:
            return 503, b"down"
        if "dexscreener.com/latest/dex/search" in url:
            return 200, json.dumps({"pairs": [pair(REAL, 900_000), pair(DECOY, 40_000)]}).encode()
        if "dexscreener.com/latest/dex/tokens/" in url:
            a = url.rsplit("/", 1)[-1].lower()
            return 200, json.dumps({"pairs": [pair(a, 900_000 if a == REAL else 40_000)]}).encode()
        if "coingecko.com/api/v3/search" in url:
            return 200, json.dumps({"coins": [{"id": "bee-protocol", "symbol": "bee"}]}).encode()
        if "coingecko.com/api/v3/coins/bee-protocol" in url and "market_chart" not in url:
            return 200, json.dumps({"id": "bee-protocol", "symbol": "bee", "name": "Bee Protocol", "platforms": {"base": w["cg_platform_contract"]},
                                    "links": {"homepage": ["https://bee.example"]}, "categories": ["AI Agents", "Base Ecosystem"], "genesis_date": None,
                                    "market_data": {"current_price": {"usd": 0.5}, "market_cap": {"usd": 5e7}, "ath": {"usd": 2.0}, "ath_date": {"usd": "2025-01-01"},
                                                    "ath_change_percentage": {"usd": -75}}, "description": {"en": "Bee things"}}).encode()
        if "/tokens/" in url and url.endswith("/info"):
            return 200, json.dumps({"data": {"attributes": {"name": "Bee Protocol", "symbol": "BEE", "websites": ["https://bee.example"], "categories": []}}}).encode()
        if "blockscout" in url:
            return 200, json.dumps({"name": "Bee Protocol", "symbol": "BEE", "decimals": "18", "holders": "4210"}).encode()
        if url.startswith("https://bee.example"):
            return 200, (f"<html>contract {REAL.upper()} </html>" if w["site_has_contract"] else "<html>no address</html>").encode()
        if "api.llama.fi/protocols" in url:
            return 200, json.dumps([{"name": "Bee Protocol", "slug": "bee-protocol", "symbol": "BEE", "gecko_id": "bee-protocol", "category": "AI", "chains": ["Base"],
                                     "tvl": 12_000_000, "change_1d": 1.2, "change_7d": 9.5, "change_1m": 30.1}]).encode()
        if "api.llama.fi/summary/fees" in url:
            return 200, json.dumps({"total24h": 12000, "total7d": 80000, "total30d": 300000}).encode()
        if "exchange.coinbase.com/products/BEE-USD" in url:
            return 404, b"{}"
        if "exchange.coinbase.com/products/BTC-USD/ticker" in url:
            return 200, b'{"price": "100000"}'
        if "exchange.coinbase.com/products/BTC-USD/candles" in url:
            return 200, json.dumps([[1_760_000_000, 70000, 72000, 71000, 71500, 10]]).encode() if "2024-" not in url else json.dumps([[1_713_571_200, 60000, 65000, 63000, 64000, 1]]).encode()
        if "/ohlcv/day" in url:
            rows = [[int(time.time()) - (900 - i) * 86400, 0.1, 0.12, 0.09, 0.1, 10] for i in range(900)]
            return 200, json.dumps({"data": {"attributes": {"ohlcv_list": rows[::-1]}}}).encode()
        if "gopluslabs" in url:
            return 200, json.dumps({"result": {REAL: {"is_honeypot": "0", "buy_tax": "0", "sell_tax": "0"}}}).encode()
        return 404, b"{}"
    monkeypatch.setattr(net, "transport", transport)
    monkeypatch.setattr(net, "MIN_INTERVAL_S", {})
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    net._cache.clear()
    return w


def test_identity_verified_and_decoy_rejected(world):
    import collect
    ev = collect.collect("$bee")
    assert ev["identity"]["status"] == "VERIFIED"
    c = ev["chosen"]
    assert c["contract"] == REAL and c["chain"] == "base"
    assert {"dexscreener", "coingecko", "geckoterminal", "explorer", "official_site"} <= set(c["sources"])
    decoy = [x for x in ev["identity"]["candidates"] if x["contract"] == DECOY][0]
    assert not decoy["verified"]
    sc = collect.scorecard_template(ev)
    assert DECOY in sc["asset"]["decoys"]
    assert ev["liquidity"]["tier"] == "Medium"  # $900K main pool
    assert "ESTIMATE" in ev["liquidity"]["depth_method"]
    assert ev["defillama"]["match"] == "gecko_id" and ev["defillama"]["fees"]["30d"] == 300000
    bb = ev["btc_benchmark"]
    assert bb["window_start"] == "2024-04-20" and bb["excess_pp"] is not None
    assert ev["cycle"]["distance_from_cycle_high_pct"] == round((100000 / 124777 - 1) * 100, 2)


def test_no_identity_anchor_is_unresolved(world):
    import collect
    world["cg_platform_contract"] = "0x" + "9" * 40  # CoinGecko maps the ticker to a different contract
    world["site_has_contract"] = False
    ev = collect.collect("BEE")
    assert ev["identity"]["status"] == "UNRESOLVED" and ev["chosen"] is None


def test_chain_and_contract_query(world):
    import collect
    q = collect.parse_query("HOOKR | Robinhood Chain", None)
    assert q == {"kind": "ticker", "symbol": "HOOKR", "chain": "robinhood"}
    assert collect.parse_query(REAL, None)["kind"] == "contract"
    ev = collect.collect(REAL)
    assert ev["identity"]["status"] == "VERIFIED" and ev["chosen"]["contract"] == REAL


def test_broken_source_is_reported_not_silent(world):
    import collect
    world["down"].add("api.llama.fi")
    ev = collect.collect("BEE")
    assert ev["source_health"]["defillama"].startswith("ERROR")
    assert any("defillama" in g for g in ev["gaps"])


def _full_scorecard(tmp_path, ev_file, **over):
    e = lambda: [{"source": "https://bee.example/docs", "quote": "Bee routes agent payments"}]  # noqa: E731
    s = lambda v: {"score": v, "evidence": e()}  # noqa: E731
    sc = {"evidence_file": str(ev_file),
          "asset": {"symbol": "BEE", "name": "Bee Protocol", "chain": "base", "contract": REAL, "identity_status": "VERIFIED",
                    "identity_sources": ["coingecko", "dexscreener", "official_site"], "decoys": [DECOY], "canonical_pool": POOL, "discovery": True},
          "gate": {"ease_of_use": s(7), "hair_on_fire": s(6), "exclusivity": s(6)},
          "cycle": {"regime": "Capitulation / Bottom Watch", "interpretation": "Bottom Watch — prioritize newborn and revived narratives."},
          "narrative": {"primary": "Software agents pay each other without banks.", "secondary": ["AI"], "perennial_roots": [4],
                        "lineage": {"perennial_root": "machines replacing jobs", "prior_crypto_narrative": "AI tokens", "current_mutation": "agent payments",
                                    "asset_expression": "BEE"}, "status": "Rising"},
          "narrative_power": {k: s(2) for k in ("one_sentence", "perennial_root", "tribe", "face_or_mystery", "fear_envy", "repetition_machine", "action_script")},
          "stage": {"stage": 2, "revival": False, "evidence": e()}, "curve": {"label": "rising", "evidence": e()},
          "constellation": s(4), "archetypes": ["Newborn Narrative"],
          "asset_expression": {k: s(2) for k in ("narrative_token_fit", "category_leadership", "distribution_reach", "product_reality", "token_capture")},
          "product_quality": s(8), "liquidity": {"tier": "Medium", "trajectory": s(4), "cycle_relative": "Underexposed / early"},
          "narrative_conversion": {"state": "Confirmed", "evidence": e()},
          "team": {"founder": {"name": "A. Founder", "high": 5, "medium": 3, "low": 2, "sources": e()},
                   "others": [{"name": "anon dev", "unverifiable": True}]},
          "smart_money_fit": s(4), "security_score": 85,
          "final_status": "EARLY ASYMMETRIC", "risk_flags": ["young token"], "recheck_triggers": ["curve turns flat"],
          "decision": {"call": "BUY", "why": "Quality and timing overlap."}, "one_sentence_overview": "Payments rail for AI agents on Base."}
    sc.update(over)
    p = tmp_path / "scorecard.json"
    p.write_text(json.dumps(sc))
    return p, sc


def test_score_full_verdict(world, tmp_path):
    import score
    ev_file = tmp_path / "evidence.json"
    ev_file.write_text(json.dumps({"cycle": {"btc_price": 100000}, "liquidity": {"main_pool": {"liquidity_usd": 900000}}}))
    p, sc = _full_scorecard(tmp_path, ev_file)
    res, probs = score.compute(sc, score.load_config())
    assert not probs, probs
    # team: founder 10, one unverifiable 0 -> (50 + 0)/6
    assert res["team"]["weighted"] == round(50 / 6, 2) and res["team"]["unverifiable"] == ["anon dev"]
    assert res["core_quality"] == round(8 + 14 + 10 + 50 / 6 + 4, 2)  # 44.33
    assert res["timing"]["total"] == 5 + 5 + 4 + 4  # stage 2 -> 5 pts
    assert res["matrix_class"] == "priority_opportunity" and res["confidence"] == "medium"
    sys.argv = ["score.py", "finalize", str(p)]
    assert score.main() == 0
    v = json.loads((tmp_path / "verdict.json").read_text())
    from hive import contracts
    assert contracts.errors_for("research.verdict", v) == []
    assert v["rank"] == "BUY" and v["confidence"] == "medium" and v["discovery"] is True and v["identity"]["decoys"] == [DECOY]
    rep = (tmp_path / "report.md").read_text()
    for section in ("## 1. Header", "## 5. Narrative Power", "## 11. Liquidity", "## 14. Core Quality", "## 19. My Decision", "UNVERIFIABLE"):
        assert section in rep


def test_fading_stage_scores_below_early(world, tmp_path):
    import score
    cfg = score.load_config()
    _, early = _full_scorecard(tmp_path, tmp_path / "x.json")
    _, fading = _full_scorecard(tmp_path, tmp_path / "x.json", stage={"stage": 5, "revival": False, "evidence": [{"source": "s"}]})
    assert score.compute(early, cfg)[0]["timing"]["stage_points"] > score.compute(fading, cfg)[0]["timing"]["stage_points"]


def test_evidence_required_and_gate_absolute(world, tmp_path):
    import score
    cfg = score.load_config()
    _, sc = _full_scorecard(tmp_path, tmp_path / "x.json")
    sc["tribe_missing"] = True
    sc["narrative_power"]["tribe"]["evidence"] = []
    _, probs = score.compute(sc, cfg)
    assert any("tribe" in x and "no evidence" in x for x in probs)
    _, sc2 = _full_scorecard(tmp_path, tmp_path / "x.json", gate={"ease_of_use": {"score": 3, "evidence": ["x"]}, "hair_on_fire": {"score": 4, "evidence": ["x"]},
                                                                   "exclusivity": {"score": 2, "evidence": ["x"]}})
    res, probs = score.compute(sc2, cfg)
    assert res["stopped_at_gate"] and any("gate is absolute" in x for x in probs)  # BUY after a failed gate is refused
    sc2["decision"]["call"] = "PASS"
    res, probs = score.compute(sc2, cfg)
    assert not probs
    assert score.verdict(sc2, res)["rank"] == "FAIL"


def test_revival_needs_catalyst(world, tmp_path):
    import score
    _, sc = _full_scorecard(tmp_path, tmp_path / "x.json", stage={"stage": 3, "revival": True, "evidence": [{"source": "s"}]})
    _, probs = score.compute(sc, score.load_config())
    assert any("NEW catalyst" in x for x in probs)


def test_unverified_identity_blocks(world, tmp_path):
    import score
    _, sc = _full_scorecard(tmp_path, tmp_path / "x.json")
    sc["asset"]["identity_status"] = "UNRESOLVED"
    _, probs = score.compute(sc, score.load_config())
    assert any("identity is UNRESOLVED" in x for x in probs)
