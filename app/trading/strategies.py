from app.trading.indicators import series

STRATEGIES = ("ema_rsi", "macd_atr", "bollinger_volume")


def evaluate(rows, strategy):
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy")
    if len(rows) < 60:
        return {"strategy": strategy, "signal": "HOLD", "reason": "Warmup: need 60 closed candles"}
    x = series(rows)
    direction = "HOLD"
    if strategy == "ema_rsi":
        if x["previous_ema9"] <= x["previous_ema21"] and x["ema9"] > x["ema21"] and 50 < x["rsi"] < 70:
            direction = "LONG"
        elif x["previous_ema9"] >= x["previous_ema21"] and x["ema9"] < x["ema21"] and 30 < x["rsi"] < 50:
            direction = "SHORT"
    elif strategy == "macd_atr":
        if x["previous_macd_hist"] <= 0 < x["macd_hist"] and x["close"] > x["ema50"] and x["rsi"] < 75:
            direction = "LONG"
        elif x["previous_macd_hist"] >= 0 > x["macd_hist"] and x["close"] < x["ema50"] and x["rsi"] > 25:
            direction = "SHORT"
    elif x["average_volume"] > 0 and x["volume"] > 1.5 * x["average_volume"] and 0.001 < x["atr"] / x["close"] < 0.05:
        if x["close"] > x["bb_upper"]:
            direction = "LONG"
        elif x["close"] < x["bb_lower"]:
            direction = "SHORT"
    result = {"strategy": strategy, "version": "1", "signal": direction,
              "candle_time": rows[-1]["open_time"], "indicators": x,
              "reason": "Closed-candle rules" if direction != "HOLD" else "No entry condition"}
    if direction != "HOLD" and x["atr"] > 0:
        sign = 1 if direction == "LONG" else -1
        result.update(entry=x["close"], stop=x["close"] - sign * 2 * x["atr"],
                      take_profit=x["close"] + sign * 4 * x["atr"], risk_reward=2,
                      trailing_stop=False, exit="Stop, target or 24-hour maximum holding time")
    else:
        result["signal"] = "HOLD"
    return result


def choose(rows):
    proposals = [evaluate(rows, name) for name in STRATEGIES]
    if len(rows) < 60:
        return {"signal": "HOLD", "reason": "Need at least 60 closed candles", "proposals": proposals}
    active = [p for p in proposals if p["signal"] != "HOLD"]
    if not active or len({p["signal"] for p in active}) > 1:
        return {"signal": "HOLD", "reason": "No signal or strategies conflict", "proposals": proposals}
    return {**active[0], "proposals": proposals}
