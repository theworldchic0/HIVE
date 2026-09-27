import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.fib_math import calculate_level
from src.structure import build
from src.zones import percent_for_price, zone_for_percent, zone_for_price, buy_zone_price_band
from src.watcher import evaluate

DAY = 86400


def candles_from(closes, start=1_700_000_000, wick=0.0):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append({"timestamp": start + i * DAY, "open": o, "high": max(o, c) * (1 + wick), "low": min(o, c), "close": c, "volume": 1})
        prev = c
    return out


def test_percent_is_inverse_of_level():
    for pct in (0, 17.4, 21.4, 61.8, 78.6, 82.6, 100):
        price = calculate_level(2.0, 12.0, pct)
        assert abs(percent_for_price(2.0, 12.0, price) - pct) < 1e-9


def test_zone_boundaries():
    assert zone_for_percent(100) == "NDCAZ"
    assert zone_for_percent(90) == "NDCAZ"
    assert zone_for_percent(82.6) == "NDCAZ"
    assert zone_for_percent(80) == "NEZ"
    assert zone_for_percent(78.6) == "NEZ"
    assert zone_for_percent(70) == "REDLEG"
    assert zone_for_percent(40) == "NUK3"
    assert zone_for_percent(20) == "NSZ"
    assert zone_for_percent(5) == "WASTELAND"
    assert zone_for_percent(0) == "WASTELAND"
    assert zone_for_percent(100.01) == "BELOW_STRUCTURE"
    assert zone_for_percent(-1) == "ABOVE_STRUCTURE"


def test_buy_band():
    lo, hi = buy_zone_price_band(1.0, 11.0)
    assert lo == 1.0 and abs(hi - (1.0 + 10 * 0.214)) < 1e-9


def test_structure_active_and_zone_entry():
    # ATL 1.0 on day 10, run to 10.0, retrace to 2.5
    closes = [5, 4, 3, 2.5, 2, 1.6, 1.4, 1.2, 1.1, 1.05, 1.0, 2, 4, 7, 10, 8, 6, 4, 3, 2.5]
    c = candles_from(closes)
    st = build(c, "base:0x" + "a" * 40)
    assert st["status"] == "ACTIVE"
    assert st["bottom_anchor"] == 1.0
    assert st["body_high"] == 10
    ev = evaluate(st, 2.5, ["NEZ", "NDCAZ"])
    assert ev["in_buy_zone"] is True  # (1 - 1.5/9)*100 = 83.3% -> NDCAZ
    ev2 = evaluate(st, 5.0, ["NEZ", "NDCAZ"])
    assert ev2["in_buy_zone"] is False and ev2["zone"] == "NUK3"


def test_both_structures_rule_is_stricter():
    closes = [5, 4, 3, 2, 1.0, 2, 4, 7, 10, 8, 6, 4, 3, 2.9, 2.8, 2.7]
    st = build(candles_from(closes, wick=0.6), "x")  # wick top 16 vs body top 10
    assert st["wick_high"] > st["body_high"]
    price = 1 + (st["wick_high"] - 1) * 0.2  # inside wick buy zone
    ev = evaluate(st, price, ["NEZ", "NDCAZ"])
    assert ev["wick"]["zone"] in ("NEZ", "NDCAZ")
    assert ev["body"]["zone"] not in ("NEZ", "NDCAZ")
    assert ev["in_buy_zone"] is False
    assert any(f["type"] == "suspicious_top_wick" for f in st["flags"])


def test_new_atl_breaks_structure():
    closes = [5, 4, 3, 2, 1.0, 2, 4, 7, 10, 8, 6, 4, 3, 2, 1.5]
    st = build(candles_from(closes), "x")
    ev = evaluate(st, 0.9, ["NEZ", "NDCAZ"])
    assert ev["broken"] and not ev["in_buy_zone"]


def test_no_expansion_needs_review():
    closes = [2, 1.9, 1.8, 1.7, 1.6, 1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 1.2, 1.3, 1.25, 1.2]
    assert build(candles_from(closes), "x")["status"] == "NEEDS_REVIEW"


def test_too_few_candles_is_data_error():
    assert build(candles_from([1, 2, 3]), "x")["status"] == "DATA_ERROR"


def test_anti_hindsight_as_of():
    closes = [5, 4, 3, 2, 1.0, 2, 4, 7, 10, 8, 6, 4, 3, 2, 1.5, 20, 30]
    c = candles_from(closes)
    early = build(c, "x", as_of_ts=c[14]["timestamp"])
    assert early["body_high"] == 10  # later 30 top not visible at the decision time
