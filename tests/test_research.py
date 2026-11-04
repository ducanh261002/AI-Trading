import asyncio
import json
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.orchestration.tools import PLAN


def candles(count=200):
    return [{"open_time": i * 300000, "close_time": (i + 1) * 300000 - 1,
             "open": "100", "high": "101", "low": "99", "close": "100", "volume": "10"}
            for i in range(count)]


def config(tmp_path, **overrides):
    return Settings(database_path=tmp_path / "research.db", market_enabled=False, _env_file=None, **overrides)


def live_fixture(app):
    market = app.state.market
    for symbol in market.symbols:
        market.store.save(symbol, "5m", candles())
    market.snapshot = lambda: {"connected": True, "state": "streaming", "symbols": [
        {"symbol": s, "price": "100", "fresh": True, "event_age_seconds": {}, "metadata": {"filters": []}}
        for s in market.symbols]}


def wait_reports(client, count=2):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = client.get("/api/research").json()
        if len(result["reports"]) >= count:
            return result
        time.sleep(.03)
    raise AssertionError("Research cycle did not report")


def test_auto_research_delegates_all_three_and_never_enters_paper(tmp_path):
    app = create_app(config(tmp_path))
    with TestClient(app) as client:
        live_fixture(app)
        # Even an armed paper account must not grant execution to research tasks.
        assert client.post("/api/paper/arm", json={"confirmation": "ENABLE PAPER ONLY"}).status_code == 200
        entered = []

        def forbidden_entry(proposal):
            entered.append(proposal)
            raise AssertionError("Research must not call paper.enter")

        app.state.trading.paper.enter = forbidden_entry
        response = client.post("/api/research", json={"enabled": True, "interval": "5m"})
        assert response.status_code == 200
        result = wait_reports(client)
        assert result["enabled"] and result["execution_allowed"] is False
        assert not entered
        for report in result["reports"]:
            assert report["analysis_only"] and len(report["comparisons"]) == 3
            assert report["sample_candles"] == 200
            assert report["profitability_certified"] is False
            assert report["warnings"] and "Chưa đủ bằng chứng" in report["conclusion"]
            run = client.get("/api/agent-cycles/" + report["run_id"]).json()
            execution = next(t for t in run["tasks"] if t["agent_id"] == "execution")
            assert execution["result"]["sent"] is False
            reporter = next(t for t in run["tasks"] if t["agent_id"] == "report")
            ceo = next(t for t in run["tasks"] if t["agent_id"] == "ceo")
            assert len(reporter["result"]["brief"]["comparisons"]) == 3
            assert ceo["result"]["summary"] == reporter["result"]["brief"]["summary"]
        previous_ids = {r["id"] for r in client.get("/api/agent-cycles").json()}
        client.post("/api/research", json={"enabled": True, "interval": "5m"})
        assert {r["id"] for r in client.get("/api/agent-cycles").json()} == previous_ids
        assert client.get("/api/portfolio").json()["positions"] == []
        assert client.post("/api/research", json={"enabled": False}).json()["enabled"] is False


def test_new_closed_candle_retriggers_but_price_updates_do_not(tmp_path):
    app = create_app(config(tmp_path))
    with TestClient(app) as client:
        live_fixture(app)
        client.post("/api/research", json={"enabled": True})
        wait_reports(client)
        assert len(client.get("/api/agent-cycles").json()) == 2
        # A quote update alone is not new backtest data.
        app.state.market.data["BTCUSDT"]["price"] = "101"
        client.post("/api/research", json={"enabled": True})
        assert len(client.get("/api/agent-cycles").json()) == 2
        app.state.market.store.save("BTCUSDT", "5m", [candles(201)[-1]])
        client.post("/api/research", json={"enabled": True})
        assert len(client.get("/api/agent-cycles").json()) == 3
        client.post("/api/research", json={"enabled": False})


def test_snapshot_and_backtest_cache_use_identical_data(tmp_path):
    app = create_app(config(tmp_path, agents_enabled=False))
    with TestClient(app):
        live_fixture(app)
        store = app.state.coordinator.store
        original = candles()
        run_id, _ = store.enqueue("BTCUSDT", "5m", "frozen-dataset", PLAN, analysis_only=True, candles=original)
        changed = {**original[-1], "close": "101", "high": "102"}
        app.state.market.store.save("BTCUSDT", "5m", [changed])
        task = next(t for t in store.run(run_id)["tasks"] if t["agent_id"] == "backtest")
        task["input"] = task["input_json"]
        assert app.state.coordinator.tools.candles(task)[-1]["close"] == "100"
        output = asyncio.run(app.state.coordinator.tools.dispatch(task))
        assert len(output["result"]["results"]) == 3
        assert all(not row["cached"] for row in output["result"]["results"])
        repeated = asyncio.run(app.state.coordinator.tools.dispatch(task))
        assert all(row["cached"] for row in repeated["result"]["results"])
        with app.state.database.connect() as con:
            assert con.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0] == 3
        # Changing a cost assumption invalidates the cache.
        app.state.trading.settings.fee_rate = .0006
        refreshed = app.state.trading.backtest("BTCUSDT", "5m", "ema_rsi", rows=original)
        assert not refreshed["cached"]


def test_stale_waits_and_research_preference_survives_restart(tmp_path):
    settings = config(tmp_path)
    with TestClient(create_app(settings)) as client:
        result = client.post("/api/research", json={"enabled": True}).json()
        assert result["enabled"] and "LIVE" in result["message"]
        assert client.get("/api/agent-cycles").json() == []
        assert client.post("/api/research", json={"enabled": True, "execute": True}).status_code == 422
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/research").json()["enabled"] is True
        assert client.get("/api/agent-cycles").json() == []
        assert client.get("/api/status").json()["halted"] is True
        client.post("/api/research", json={"enabled": False})
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/research").json()["enabled"] is False


def test_old_schema_migrates_without_losing_backtests(tmp_path):
    settings = config(tmp_path)
    from app.db import Database
    database = Database(settings.database_path)
    database.initialize()
    with database.connect() as con:
        con.execute("CREATE TABLE agent_runs(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,interval TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,finished_at TEXT)")
        con.execute("CREATE TABLE backtest_results(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,symbol TEXT NOT NULL,interval TEXT NOT NULL,payload TEXT NOT NULL)")
        con.execute("INSERT INTO backtest_results VALUES('legacy','2026-11-01','BTCUSDT','5m','{}')")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/research").status_code == 200
        with database.connect() as con:
            assert con.execute("SELECT COUNT(*) FROM backtest_results WHERE id='legacy'").fetchone()[0] == 1
            assert "analysis_only" in {row["name"] for row in con.execute("PRAGMA table_info(tasks)")}
