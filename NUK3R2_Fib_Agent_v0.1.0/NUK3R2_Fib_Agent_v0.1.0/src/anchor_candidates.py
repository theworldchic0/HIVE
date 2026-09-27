from .fib_math import candle_body_high

def candidate_anchors(candles):
    if not candles:
        raise ValueError("No candles supplied.")
    wick = max(candles, key=lambda c: c["high"])
    body = max(candles, key=lambda c: candle_body_high(c["open"], c["close"]))
    return {
        "wick_high": wick["high"],
        "wick_timestamp": wick["timestamp"],
        "wick_body_high": candle_body_high(wick["open"], wick["close"]),
        "body_high": candle_body_high(body["open"], body["close"]),
        "body_timestamp": body["timestamp"]
    }
