"""NUK3R2 zone classification. Orientation (unchanged from fib_math): 100% = bottom, 0% = top.

percent_for_price is the inverse of fib_math.calculate_level:
    price = bottom + (top - bottom) * (1 - pct/100)  <=>  pct = (1 - (price - bottom)/(top - bottom)) * 100

Zone boundaries (from config zone_metadata), each zone includes its lower-percent edge except
NDCAZ which also includes 100 exactly:
    NDCAZ  100  .. 82.6      NUK3       61.8 .. 21.4
    NEZ    82.6 .. 78.6      NSZ        21.4 .. 17.4
    REDLEG 78.6 .. 61.8      WASTELAND  17.4 .. 0
Price under the bottom anchor (pct > 100) is BELOW_STRUCTURE — the structure is broken, never
a buy. Price above the top (pct < 0) is ABOVE_STRUCTURE.
"""
from __future__ import annotations

ZONES = (  # (name, low_pct, high_pct) — ordered bottom to top
    ("NDCAZ", 82.6, 100.0),
    ("NEZ", 78.6, 82.6),
    ("REDLEG", 61.8, 78.6),
    ("NUK3", 21.4, 61.8),
    ("NSZ", 17.4, 21.4),
    ("WASTELAND", 0.0, 17.4),
)


def percent_for_price(bottom: float, top: float, price: float) -> float:
    if top <= bottom:
        raise ValueError("Top anchor must be greater than bottom anchor.")
    return (1.0 - (price - bottom) / (top - bottom)) * 100.0


def zone_for_percent(pct: float) -> str:
    if pct > 100.0:
        return "BELOW_STRUCTURE"
    if pct < 0.0:
        return "ABOVE_STRUCTURE"
    if pct >= 82.6:
        return "NDCAZ"
    for name, lo, hi in ZONES[1:]:
        if lo <= pct < hi:
            return name
    return "WASTELAND"  # pct == 0 exactly


def zone_for_price(bottom: float, top: float, price: float) -> tuple[str, float]:
    pct = percent_for_price(bottom, top, price)
    return zone_for_percent(pct), pct


def buy_zone_price_band(bottom: float, top: float, zones=("NEZ", "NDCAZ")) -> tuple[float, float]:
    """Price band [low, high] covered by the given (contiguous) zones — for display and limit orders."""
    from .fib_math import calculate_level
    spans = [(lo, hi) for name, lo, hi in ZONES if name in zones]
    if not spans:
        raise ValueError("no zones")
    lo_pct = min(s[0] for s in spans)
    hi_pct = max(s[1] for s in spans)
    return calculate_level(bottom, top, hi_pct), calculate_level(bottom, top, lo_pct)
