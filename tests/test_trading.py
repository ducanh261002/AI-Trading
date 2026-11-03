import json
import time
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.trading.backtest import run_backtest
from app.trading.indicators import series
from app.trading.risk import RiskManager
from app.trading.strategies import STRATEGIES, evaluate

FILTERS = [{"filterType": "PRICE_FILTER", "tickSize": "0.01", "minPrice": "0.01", "maxPrice": "1000000"},
           {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
           {"filterType": "MIN_NOTIONAL", "notional": "5"}]


def bars(count=200):
    return [{"open_time": i * 300000, "close_time": (i+1)*300000-1, "open": "100", "high": "105",
             "low": "97", "close": "100", "volume": "100"} for i in range(count)]


def proposal():
    return {"symbol": "BTCUSDT", "interval": "5m", "strategy": "ema_rsi", "candle_time": 1,
            "signal": "LONG", "entry": 100, "stop": 98, "take_profit": 104}


def portfolio():
    return {"equity": 10000, "peak_equity": 10000, "day_start_equity": 10000,
            "free_margin": 10000, "positions": []}


def test_indicators_flat_market_and_strategies():
    result = series(bars())
    assert result["rsi"] == 50 and result["macd"] == 0
    assert result["ema50"] == 100 and result["bb_mid"] == 100
    assert result["atr"] == 8
    for strategy in STRATEGIES:
        assert evaluate(bars(), strategy)["signal"] == "HOLD"
        assert evaluate(bars(20), strategy)["signal"] == "HOLD"


@pytest.mark.parametrize("case", ["halt", "stale", "daily", "drawdown", "count", "duplicate", "exposure", "missing_filters", "bad_stop"])
def test_risk_rejects_limits(case):
    settings = Settings(_env_file=None)
    p, account, filters = proposal(), portfolio(), FILTERS
    halted, fresh = case == "halt", case != "stale"
    if case == "daily":
        account["equity"] = 9700
    elif case == "drawdown":
        account.update(equity=8900, day_start_equity=8900)
    elif case == "count":
        account["positions"] = [{"symbol": name, "quantity": 1, "entry": 1} for name in ("A", "B", "C")]
    elif case == "duplicate":
        account["positions"] = [{"symbol": "BTCUSDT", "quantity": 1, "entry": 100}]
    elif case == "exposure":
        account["positions"] = [{"symbol": "ETHUSDT", "quantity": 100, "entry": 100}]
    elif case == "missing_filters":
        filters = []
    elif case == "bad_stop":
        p["stop"] = 110
    assert RiskManager(settings).review(p, account, filters, fresh, halted)["approved"] is False


def test_risk_sizes_with_costs_and_rounding():
    result = RiskManager(Settings(_env_file=None)).review(proposal(), portfolio(), FILTERS, True, False)
    assert result["approved"] is True
    assert float(result["estimated_loss_including_costs"]) <= 50
    assert float(result["quantity"]) * 100 <= 10000


def test_backtest_next_open_stop_first_and_holdout(monkeypatch):
    def signal(rows, name):
        assert rows[-1]["open_time"] < rows[0]["open_time"] + len(rows) * 300000
        return {"signal": "LONG", "entry": 100, "stop": 98, "take_profit": 104}
    monkeypatch.setattr("app.trading.backtest.evaluate", signal)
    settings = Settings(_env_file=None, fee_rate=0, slippage_rate=0, funding_rate=0)
    result = run_backtest(bars(), "ema_rsi", settings)
    assert 0 < result["trade_count"] <= 5  # Daily risk gate stops further entries.
    assert all(trade["reason"] == "stop" and trade["net_pnl"] < 0 for trade in result["trades"])
    assert result["trades"][0]["opened_at"] == bars()[60]["open_time"]
    assert result["holdout"]["split_index"] == 140
    assert result["holdout"]["testing"]["net_return"] < 0


def test_paper_lifecycle_idempotency_and_backup(tmp_path):
    settings = Settings(database_path=tmp_path / "db.sqlite3", market_enabled=False, _env_file=None)
    app = create_app(settings)
    with TestClient(app) as client:
        market = app.state.market
        market.snapshot = lambda: {"connected": True, "symbols": [{"symbol": "BTCUSDT", "price": "100", "fresh": True, "metadata": {"filters": FILTERS}}]}
        assert client.post("/api/paper/arm", json={"confirmation": "ENABLE PAPER ONLY"}).status_code == 200
        paper = app.state.trading.paper
        first = paper.enter(proposal())
        assert first["sent"] and not first["exchange_order_sent"]
        assert paper.enter(proposal())["sent"] is False
        pos = paper.portfolio()["positions"][0]
        closed = {"open_time": pos["opened_at"] + 1, "close_time": pos["opened_at"] + 300000,
                  "open": "100", "high": "101", "low": "97", "close": "98", "volume": "1"}
        market.store.save("BTCUSDT", "5m", [closed])
        paper.update_positions()
        assert paper.portfolio()["positions"] == []
        count = len(paper.ledger())
        paper.update_positions()
        assert len(paper.ledger()) == count
        assert paper.performance()["trade_count"] == 1
        assert paper.portfolio()["cash"] < 10000
        app.state.trading.maintenance()
        assert len(app.state.trading.reports()) == 3
        assert list((tmp_path / "backups").glob("*.sqlite3"))
        assert client.post("/api/orders").status_code == 403
        snapshot_cash = paper.portfolio()["cash"]
        with sqlite3.connect(settings.database_path) as source, sqlite3.connect(tmp_path / "restored.sqlite3") as destination:
            source.backup(destination)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/performance").json()["trade_count"] == 1
    restored = Settings(database_path=tmp_path / "restored.sqlite3", market_enabled=False, _env_file=None)
    with TestClient(create_app(restored)) as client:
        assert client.get("/api/performance").json()["trade_count"] == 1
        assert client.get("/api/portfolio").json()["cash"] == snapshot_cash
        assert client.get("/api/status").json()["halted"] is True


def test_paper_arm_requires_freshness_and_confirmation(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path / "db", market_enabled=False, _env_file=None))) as client:
        assert client.post("/api/paper/arm", json={}).status_code == 422
        assert client.post("/api/paper/arm", json={"confirmation": "ENABLE PAPER ONLY"}).status_code == 409
        assert client.get("/api/portfolio").json()["simulated"] is True
        assert client.post("/api/backtests", json={}).status_code == 409
