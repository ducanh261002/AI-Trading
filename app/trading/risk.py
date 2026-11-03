from decimal import Decimal, ROUND_DOWN, ROUND_UP


def D(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite risk input")
    return result


class RiskManager:
    def __init__(self, settings):
        self.settings = settings

    def review(self, proposal, portfolio, filters, fresh, halted):
        reasons = []
        if halted:
            reasons.append("Kill Switch active")
        if not fresh:
            reasons.append("Market data stale or incomplete")
        if proposal.get("signal") not in {"LONG", "SHORT"}:
            reasons.append("No actionable signal")
        if reasons:
            return {"approved": False, "reasons": reasons}
        try:
            equity = D(portfolio["equity"])
            peak, day_start = D(portfolio["peak_equity"]), D(portfolio["day_start_equity"])
            if equity <= 0 or peak <= 0 or day_start <= 0:
                raise ValueError("Invalid equity")
            if equity <= day_start * (1 - D(self.settings.daily_loss_limit)):
                reasons.append("Daily loss limit")
            if equity <= peak * (1 - D(self.settings.max_drawdown)):
                reasons.append("Maximum drawdown")
            positions = portfolio["positions"]
            if len(positions) >= self.settings.max_positions:
                reasons.append("Position count limit")
            if any(p["symbol"] == proposal["symbol"] for p in positions):
                reasons.append("Existing symbol position; averaging is forbidden")
            specs = {f["filterType"]: f for f in filters}
            tick, step = D(specs["PRICE_FILTER"]["tickSize"]), D(specs["LOT_SIZE"]["stepSize"])
            if tick <= 0 or step <= 0:
                raise ValueError("Invalid exchange filters")
            side = proposal["signal"]
            rounding = ROUND_DOWN if side == "LONG" else ROUND_UP
            entry = (D(proposal["entry"]) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
            stop = (D(proposal["stop"]) / tick).to_integral_value(rounding=rounding) * tick
            target = (D(proposal["take_profit"]) / tick).to_integral_value(rounding=ROUND_DOWN if side == "LONG" else ROUND_UP) * tick
            if not (0 < stop < entry < target if side == "LONG" else 0 < target < entry < stop):
                raise ValueError("Invalid stop/target geometry")
            distance = abs(entry - stop)
            if abs(target - entry) / distance < D("1.5"):
                reasons.append("Risk/reward below 1.5")
            leverage = min(self.settings.max_leverage, 2)
            # Conservative paper-only liquidation proxy, not exchange liquidation.
            # Real/testnet submission needs actual maintenance brackets and margin.
            liquidation_buffer = entry * (D(1) / leverage - D("0.05"))
            if distance >= liquidation_buffer * D("0.5"):
                reasons.append("Stop too close to estimated liquidation zone")
            costs = entry * (2 * D(self.settings.fee_rate) + 2 * D(self.settings.slippage_rate) + 3 * abs(D(self.settings.funding_rate)))
            risk_budget = equity * D(self.settings.risk_per_trade)
            exposed = sum(D(p["quantity"]) * D(p["entry"]) for p in positions)
            available = min(equity * D(self.settings.max_exposure) - exposed, D(portfolio["free_margin"]) * leverage)
            quantity = min(risk_budget * D("0.98") / (distance + costs), max(D(0), available) * D("0.98") / entry)
            quantity = (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step
            lot = specs["LOT_SIZE"]
            quantity = min(quantity, D(lot["maxQty"]))
            quantity = (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step
            minimum = specs.get("MIN_NOTIONAL", {}).get("notional", specs.get("NOTIONAL", {}).get("minNotional", "0"))
            if quantity < D(lot["minQty"]) or quantity <= 0 or quantity * entry < D(minimum):
                reasons.append("Quantity/notional below exchange minimum")
            price_filter = specs["PRICE_FILTER"]
            for price in (entry, stop, target):
                if not D(price_filter.get("minPrice", 0)) <= price <= D(price_filter.get("maxPrice", "1e30")):
                    reasons.append("Price outside exchange filter")
            if reasons:
                return {"approved": False, "reasons": reasons}
            return {"approved": True, "quantity": str(quantity), "entry": str(entry), "stop": str(stop),
                    "take_profit": str(target), "leverage": leverage, "risk_budget": str(risk_budget),
                    "estimated_loss_including_costs": str(quantity * (distance + costs)),
                    "scope": "Paper only; exchange liquidation is not verified"}
        except (KeyError, ValueError, ArithmeticError, TypeError):
            return {"approved": False, "reasons": ["Missing or invalid risk/account/exchange metadata"]}
