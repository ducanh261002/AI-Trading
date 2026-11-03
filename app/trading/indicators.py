import math
import statistics


def ema(values, period):
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(float(value) * alpha + result[-1] * (1 - alpha))
    return result


def series(rows):
    closes = [float(row["close"]) for row in rows]
    if any(not math.isfinite(value) or value <= 0 for value in closes):
        raise ValueError("Invalid candles")
    if len(rows) < 60:
        raise ValueError("At least 60 closed candles required")
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    signal = ema(macd, 9)
    gains = [max(0, b - a) for a, b in zip(closes, closes[1:])]
    losses = [max(0, a - b) for a, b in zip(closes, closes[1:])]
    gain, loss = sum(gains[:14]) / 14, sum(losses[:14]) / 14
    for g, l in zip(gains[14:], losses[14:]):
        gain, loss = (gain * 13 + g) / 14, (loss * 13 + l) / 14
    rsi = 50 if gain == loss == 0 else 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    ranges = []
    for i, row in enumerate(rows):
        high, low = float(row["high"]), float(row["low"])
        previous = closes[max(0, i - 1)]
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    atr = sum(ranges[:14]) / 14
    for value in ranges[14:]:
        atr = (atr * 13 + value) / 14
    mid, sd = statistics.mean(closes[-20:]), statistics.pstdev(closes[-20:])
    e9, e21, e50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    return {"close": closes[-1], "previous_close": closes[-2], "ema9": e9[-1], "ema21": e21[-1],
            "ema50": e50[-1], "previous_ema9": e9[-2], "previous_ema21": e21[-2], "rsi": rsi,
            "macd": macd[-1], "macd_signal": signal[-1], "macd_hist": macd[-1] - signal[-1],
            "previous_macd_hist": macd[-2] - signal[-2], "atr": atr,
            "bb_mid": mid, "bb_upper": mid + 2 * sd, "bb_lower": mid - 2 * sd,
            "volume": float(rows[-1]["volume"]),
            "average_volume": statistics.mean(float(r["volume"]) for r in rows[-21:-1])}
