"""Deterministic NUK3R2 structure builder (rules v0.2.0 — see config structure_rules).

Given candles known at the decision time (never later ones — anti-hindsight), build BOTH the
Wick-High and the Body-High structure from the same bottom anchor:

  bottom      = lowest low in the study window (the ATL within available history)
  wick_high   = highest High strictly AFTER the bottom candle
  body_high   = highest max(Open, Close) strictly AFTER the bottom candle

It returns a status instead of guessing:
  DATA_ERROR    too few candles / non-positive prices
  NEEDS_REVIEW  no validated expansion after the ATL (move < min_expansion_multiple, or the ATL
                is too recent to have a structure) — never tradable
  ACTIVE        both structures valid

Suspicious wicks are FLAGGED (with their extension %), never silently removed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .fib_math import calculate_structure, candle_body_high, wick_extension_pct

DEFAULT_RULES = {
    "min_expansion_multiple": 2.0,
    "min_candles_after_bottom": 3,
    "young_token_days": 90,
    "min_candles": 14,
    "suspicious_wick_extension_pct": 50.0,
}


def _ts(c) -> int:
    t = c["timestamp"]
    if isinstance(t, (int, float)):
        return int(t)
    return int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp())


def build(candles: list[dict], asset_id: str = "", rules: dict | None = None, as_of_ts: int | None = None) -> dict:
    r = {**DEFAULT_RULES, **(rules or {})}
    cs = sorted((c for c in candles if as_of_ts is None or _ts(c) <= as_of_ts), key=_ts)
    out = {"asset_id": asset_id, "rules_version": "0.2.0", "candles_used": len(cs), "flags": []}
    if len(cs) < r["min_candles"]:
        return {**out, "status": "DATA_ERROR", "reason": f"only {len(cs)} candles (< {r['min_candles']})"}
    if any(min(c["open"], c["high"], c["low"], c["close"]) <= 0 for c in cs):
        return {**out, "status": "DATA_ERROR", "reason": "non-positive price in candles"}

    span_days = (_ts(cs[-1]) - _ts(cs[0])) / 86400
    out["study_mode"] = "young" if span_days < r["young_token_days"] else "mature"
    out["data_coverage"] = {"first": _ts(cs[0]), "last": _ts(cs[-1]), "span_days": round(span_days, 1)}

    bi = min(range(len(cs)), key=lambda i: (cs[i]["low"], i))
    bottom_c = cs[bi]
    bottom = bottom_c["low"]
    after = cs[bi + 1:]
    out["bottom_anchor"] = bottom
    out["bottom_timestamp"] = _ts(bottom_c)
    bottom_body_low = min(bottom_c["open"], bottom_c["close"])
    if bottom_body_low > 0 and (bottom_body_low - bottom) / bottom_body_low * 100 > r["suspicious_wick_extension_pct"]:
        out["flags"].append({"type": "suspicious_bottom_wick", "wick_low": bottom, "body_low": bottom_body_low})

    if len(after) < r["min_candles_after_bottom"]:
        return {**out, "status": "NEEDS_REVIEW", "reason": "ATL is too recent: no structure has formed after it"}

    wc = max(after, key=lambda c: (c["high"], -_ts(c)))
    bc = max(after, key=lambda c: (candle_body_high(c["open"], c["close"]), -_ts(c)))
    wick_high = wc["high"]
    body_high = candle_body_high(bc["open"], bc["close"])
    out.update({"wick_high": wick_high, "wick_timestamp": _ts(wc), "body_high": body_high, "body_timestamp": _ts(bc)})
    ext = wick_extension_pct(wick_high, candle_body_high(wc["open"], wc["close"]))
    out["wick_extension_pct"] = round(ext, 2)
    if ext > r["suspicious_wick_extension_pct"]:
        out["flags"].append({"type": "suspicious_top_wick", "extension_pct": round(ext, 2)})

    if body_high / bottom < r["min_expansion_multiple"]:
        return {**out, "status": "NEEDS_REVIEW",
                "reason": f"expansion {body_high / bottom:.2f}x < {r['min_expansion_multiple']}x — no validated structural high"}

    sid_src = f"{asset_id}|{out['bottom_timestamp']}|{bottom}|{out['wick_timestamp']}|{wick_high}|{out['body_timestamp']}|{body_high}"
    out["structure_id"] = "FIB-" + hashlib.sha1(sid_src.encode()).hexdigest()[:12]
    out["levels"] = {"wick_high": calculate_structure(bottom, wick_high), "body_high": calculate_structure(bottom, body_high)}
    out["status"] = "ACTIVE"
    out["built_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return out
