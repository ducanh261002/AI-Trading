from decimal import Decimal, InvalidOperation

INTERVALS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def number(value, positive=False):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid market number") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("Invalid market number")
    return str(result)


def candle(row):
    result = {"open_time": int(row[0]), "close_time": int(row[6]),
              "open": number(row[1], True), "high": number(row[2], True),
              "low": number(row[3], True), "close": number(row[4], True),
              "volume": number(row[5])}
    if result["open_time"] < 0 or result["close_time"] < result["open_time"]:
        raise ValueError("Invalid candle time")
    low, high = Decimal(result["low"]), Decimal(result["high"])
    if not low <= Decimal(result["open"]) <= high or not low <= Decimal(result["close"]) <= high:
        raise ValueError("Invalid candle range")
    return result


def levels(rows, reverse):
    parsed = [(number(p, True), number(q)) for p, q in rows]
    return sorted([row for row in parsed if Decimal(row[1]) > 0],
                  key=lambda row: Decimal(row[0]), reverse=reverse)[:20]
