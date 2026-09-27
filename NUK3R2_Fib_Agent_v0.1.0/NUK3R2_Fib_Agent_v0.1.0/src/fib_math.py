LEVELS = (100.0, 82.6, 78.6, 61.8, 21.4, 17.4, 0.0)

def calculate_level(bottom, top, percent):
    if top <= bottom:
        raise ValueError("Top anchor must be greater than bottom anchor.")
    return bottom + (top - bottom) * (1.0 - percent / 100.0)

def calculate_structure(bottom, top):
    return {str(level): calculate_level(bottom, top, level) for level in LEVELS}

def candle_body_high(open_price, close_price):
    return max(open_price, close_price)

def candle_body_low(open_price, close_price):
    return min(open_price, close_price)

def wick_extension_pct(high, body_high):
    if body_high <= 0:
        raise ValueError("Body high must be positive.")
    return (high - body_high) / body_high * 100.0
