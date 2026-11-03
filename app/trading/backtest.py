import math

from app.trading.strategies import evaluate


def exit_price(position, bar):
    sign = 1 if position["side"] == "LONG" else -1
    opening, high, low = (float(bar[key]) for key in ("open", "high", "low"))
    stop, target = position["stop"], position["take_profit"]
    # Stop wins if both levels occur in a candle with unknown intrabar path.
    if (low <= stop if sign == 1 else high >= stop):
        return (min(opening, stop) if sign == 1 else max(opening, stop)), "stop"
    if (high >= target if sign == 1 else low <= target):
        return target, "target"
    if bar["close_time"] - position["opened_at"] >= 86_400_000:
        return float(bar["close"]), "maximum_holding_time"
    return None


def funding_charge(position, end_time, rate):
    start = position.get("funding_time", position["opened_at"])
    periods = max(0, end_time // 28_800_000 - start // 28_800_000)
    sign = 1 if position["side"] == "LONG" else -1
    return periods * position["entry"] * position["quantity"] * rate * sign


def _simulate(rows, strategy, settings):
    if len(rows) < 120:
        raise ValueError("Backtest needs at least 120 closed candles")
    for a, b in zip(rows, rows[1:]):
        if b["open_time"] <= a["open_time"]:
            raise ValueError("Candles must be strictly ordered")
    balance = float(settings.paper_initial_balance)
    initial = balance
    position = None
    trades, curve = [], []
    fee, slip = settings.fee_rate, settings.slippage_rate
    trading_day, day_start, risk_peak = None, balance, balance
    for i in range(60, len(rows)):
        bar = rows[i]
        day = (bar["open_time"] + 7 * 3600000) // 86400000
        if day != trading_day:
            trading_day = day
            day_start = balance + (0 if position is None else (float(bar["open"]) - position["entry"]) * position["quantity"] * (1 if position["side"] == "LONG" else -1))
        allow_entry = balance > max(0, day_start * (1 - settings.daily_loss_limit), risk_peak * (1 - settings.max_drawdown))
        if position is None and allow_entry:
            proposal = evaluate(rows[:i], strategy)
            if proposal["signal"] != "HOLD":
                sign = 1 if proposal["signal"] == "LONG" else -1
                entry = float(bar["open"]) * (1 + sign * slip)
                distance = abs(proposal["entry"] - proposal["stop"])
                budget = balance * settings.risk_per_trade
                quantity = min(budget / (distance + entry * (2 * fee + 2 * slip + 3 * abs(settings.funding_rate))), balance / entry)
                entry_fee = entry * quantity * fee
                balance -= entry_fee
                position = {"side": proposal["signal"], "entry": entry, "quantity": quantity,
                            "stop": entry - sign * distance, "take_profit": entry + sign * 2 * distance,
                            "opened_at": bar["open_time"], "entry_fee": entry_fee, "funding_paid": 0.0,
                            "funding_time": bar["open_time"]}
        if position:
            funding = funding_charge(position, bar["close_time"], settings.funding_rate)
            balance -= funding
            position["funding_paid"] += funding
            position["funding_time"] = bar["close_time"]
            exit = exit_price(position, bar)
            if exit:
                price, reason = exit
                sign = 1 if position["side"] == "LONG" else -1
                price *= 1 - sign * slip
                pnl = (price - position["entry"]) * position["quantity"] * sign
                close_fee = price * position["quantity"] * fee
                balance += pnl - close_fee
                trades.append({"side": position["side"], "opened_at": position["opened_at"], "closed_at": bar["close_time"],
                               "entry": position["entry"], "exit": price, "quantity": position["quantity"],
                               "net_pnl": pnl - close_fee - position["entry_fee"] - position["funding_paid"],
                               "fees": close_fee + position["entry_fee"], "funding": position["funding_paid"], "reason": reason})
                position = None
        unrealized = 0 if not position else (float(bar["close"]) - position["entry"]) * position["quantity"] * (1 if position["side"] == "LONG" else -1)
        curve.append(balance + unrealized)
        risk_peak = max(risk_peak, curve[-1])
    if position:
        price = float(rows[-1]["close"]) * (1 - (1 if position["side"] == "LONG" else -1) * slip)
        sign = 1 if position["side"] == "LONG" else -1
        pnl = (price - position["entry"]) * position["quantity"] * sign
        close_fee = price * position["quantity"] * fee
        balance += pnl - close_fee
        trades.append({"side": position["side"], "entry": position["entry"], "exit": price,
                       "quantity": position["quantity"], "opened_at": position["opened_at"], "closed_at": rows[-1]["close_time"],
                       "net_pnl": pnl - close_fee - position["entry_fee"] - position["funding_paid"],
                       "fees": close_fee + position["entry_fee"], "funding": position["funding_paid"], "reason": "end_of_sample"})
    peak, drawdown = initial, 0.0
    for equity in [*curve, balance]:
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    assert math.isfinite(balance)
    return {"strategy": strategy, "sample_candles": len(rows), "trade_count": len(trades),
            "initial_equity": initial, "final_equity": balance, "net_return": balance / initial - 1,
            "max_drawdown": drawdown, "win_rate": sum(t["net_pnl"] > 0 for t in trades) / len(trades) if trades else None,
            "expectancy": sum(t["net_pnl"] for t in trades) / len(trades) if trades else None,
            "trades": trades[-200:], "equity_curve": curve,
            "assumptions": {"fee_rate_each_side": fee, "slippage_each_side": slip,
                            "funding_rate_every_8h": settings.funding_rate, "funding_is_assumed": True,
                            "stop_first_same_bar": True, "entry": "next candle open", "exchange_filters": "not simulated"},
            "validation": "In-sample simulation only; no out-of-sample profitability claim"}


def run_backtest(rows, strategy, settings):
    result = _simulate(rows, strategy, settings)
    if len(rows) >= 200:
        split = int(len(rows) * .7)
        training = _simulate(rows[:split], strategy, settings)
        holdout = _simulate(rows[split - 60:], strategy, settings)
        result["holdout"] = {"split_index": split, "split_time": rows[split]["open_time"],
                              "method": "Fixed parameters, 70/30 chronological split, 60 prior warmup bars; no tuning",
                              "training": {k: training[k] for k in ("trade_count", "net_return", "max_drawdown")},
                              "testing": {k: holdout[k] for k in ("trade_count", "net_return", "max_drawdown")}}
        result["validation"] = "Chronological holdout simulation; still requires longer history and forward paper validation"
    return result
