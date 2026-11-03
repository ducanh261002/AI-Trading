import asyncio
import time
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.market.engine import MarketEngine
from app.market.models import INTERVALS, candle, number
from app.market.rest import BinanceREST, MarketAccessError


@pytest.fixture
def engine(tmp_path):
    settings = Settings(database_path=tmp_path / "market.db", market_enabled=False,
                        market_symbols="BTCUSDT", candle_limit=50, _env_file=None)
    database = Database(settings.database_path)
    database.initialize()
    result = MarketEngine(settings, database, rest=AsyncMock(used_weight=None))
    result.store.initialize()
    return result


def kline(interval="5m", closed=False, start=0):
    return {"e": "kline", "s": "BTCUSDT", "E": int(time.time() * 1000),
            "k": {"t": start, "T": start + INTERVALS[interval] - 1, "i": interval,
                  "o": "100", "h": "110", "l": "90", "c": "105", "v": "2", "x": closed}}


def trade(identifier=1):
    return {"e": "aggTrade", "s": "BTCUSDT", "E": int(time.time() * 1000),
            "T": int(time.time() * 1000), "a": identifier, "p": "101", "q": "0.2"}


def test_streams_parser_and_staleness(engine):
    assert "/market/stream?streams=btcusdt@aggTrade/" in engine.urls()["market"]
    assert "/public/stream?streams=btcusdt@depth20@500ms" in engine.urls()["public"]
    engine.channels = {"market": True, "public": True}
    for interval in INTERVALS:
        engine.handle({"data": kline(interval)})
    engine.handle({"data": trade()})
    engine.handle({"data": trade()})
    assert len(engine.data["BTCUSDT"]["trades"]) == 1
    engine.handle({"data": {"e": "depthUpdate", "s": "BTCUSDT", "E": int(time.time() * 1000),
                            "u": 10, "b": [["100", "1"], ["99", "2"]], "a": [["102", "2"]]}})
    assert engine.snapshot()["connected"] is True
    engine.data["BTCUSDT"]["received"]["book"] -= 60
    assert engine.snapshot()["connected"] is False
    engine.data["BTCUSDT"]["received"]["book"] = time.monotonic()
    engine.data["BTCUSDT"]["event_times"]["book"] -= 60_000
    assert engine.snapshot()["connected"] is False
    assert engine.snapshot()["execution_available"] is False


def test_closed_candles_retention_and_gap(engine):
    engine.handle(kline(closed=False))
    assert engine.store.read("BTCUSDT", "5m") == []
    for i in range(55):
        engine.handle(kline(closed=True, start=i * 300_000))
    rows = engine.store.read("BTCUSDT", "5m")
    assert len(rows) == 50
    assert rows[0]["open_time"] == 5 * 300_000
    engine.handle(kline(closed=True, start=54 * 300_000))
    assert len(engine.store.read("BTCUSDT", "5m")) == 50
    with pytest.raises(ValueError, match="gap"):
        engine.handle(kline(closed=True, start=57 * 300_000))
    for value in ("NaN", "Infinity", "-1", "secret"):
        with pytest.raises(ValueError):
            number(value)
    with pytest.raises(ValueError, match="range"):
        candle([0, "100", "90", "80", "85", "1", 1])


def test_rest_rate_limit_and_access(monkeypatch):
    async def run():
        calls, sleeps = [], []

        async def pause(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr("app.market.rest.asyncio.sleep", pause)

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
            return httpx.Response(200, json={"serverTime": 123}, headers={"x-mbx-used-weight-1m": "3"})

        rest = BinanceREST(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://fapi.binance.com"))
        assert (await rest.get("/fapi/v1/time"))["serverTime"] == 123
        assert len(calls) == 2 and max(sleeps) > 1
        assert rest.used_weight == "3"
        await rest.close()
        rest = BinanceREST(httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(451)), base_url="https://fapi.binance.com"))
        with pytest.raises(MarketAccessError):
            await rest.get("/fapi/v1/time")
        await rest.close()

    asyncio.run(run())


def test_bootstrap_reconnect_and_cancellation(engine, monkeypatch):
    async def run():
        count = 0
        synced = asyncio.Event()
        original_sleep = asyncio.sleep

        async def fast_sleep(seconds):
            await original_sleep(min(seconds, 0.001))

        monkeypatch.setattr("app.market.engine.asyncio.sleep", fast_sleep)

        async def bootstrap():
            nonlocal count
            count += 1
            if count == 2:
                synced.set()

        async def consume(channel, url):
            if count == 1:
                raise ConnectionError("Simulated network loss")
            await asyncio.Event().wait()

        engine.bootstrap = bootstrap
        engine.consume = consume
        engine.watchdog = AsyncMock(side_effect=lambda: None)
        engine.task = asyncio.create_task(engine.run())
        await asyncio.wait_for(synced.wait(), 1)
        assert engine.reconnects == 1
        assert not engine.snapshot()["connected"]
        await engine.stop()
        assert engine.task.cancelled()
        engine.rest.close.assert_awaited_once()

    asyncio.run(run())


def test_api_offline_and_validation(tmp_path):
    settings = Settings(database_path=tmp_path / "state.db", market_enabled=False, _env_file=None)
    with TestClient(create_app(settings)) as client:
        snapshot = client.get("/api/market").json()
        assert snapshot["state"] == "disabled" and not snapshot["connected"]
        assert all(row["price"] is None for row in snapshot["symbols"])
        assert client.get("/api/candles/BTCUSDT").json()["candles"] == []
        assert client.get("/api/candles/UNKNOWN").status_code == 422
        assert client.get("/api/candles/BTCUSDT?interval=1s").status_code == 422
        assert client.get("/api/health").json()["phase"] == 7
    for symbols in ("BTCUSDT,BTCUSDT", "BTC/USDT", "ETHUSDT,", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT"):
        with pytest.raises(ValueError):
            Settings(market_symbols=symbols, _env_file=None)


def test_bootstrap_uses_metadata_and_closed_candles(engine):
    timestamp = int(time.time() * 1000)

    async def get(path, **params):
        if path == "/fapi/v1/exchangeInfo":
            return {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT",
                                 "contractType": "PERPETUAL", "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001"}]}]}
        if path == "/fapi/v1/time":
            return {"serverTime": timestamp}
        assert path == "/fapi/v1/klines"
        step = INTERVALS[params["interval"]]
        current = timestamp // step * step
        return [[start, "100", "110", "90", "105", "3", start + step - 1]
                for start in (current - 2 * step, current - step, current)]

    engine.rest.get = AsyncMock(side_effect=get)
    asyncio.run(engine.bootstrap())
    assert engine.metadata["BTCUSDT"]["filters"][0]["stepSize"] == "0.001"
    for interval in INTERVALS:
        rows = engine.store.read("BTCUSDT", interval)
        assert len(rows) == 2
        assert all(row["close_time"] < timestamp for row in rows)
    assert engine.rest.get.await_count == 6


def test_real_websocket_transport_with_local_fixture(engine, monkeypatch):
    """Exercise actual sockets/framing; this is not a Binance live test."""
    from websockets.asyncio.server import serve

    async def run():
        async def handler(socket):
            if socket.request.path.startswith("/market/"):
                packets = [trade(), *(kline(interval) for interval in INTERVALS)]
            else:
                packets = [{"e": "depthUpdate", "s": "BTCUSDT", "E": int(time.time() * 1000),
                            "u": 1, "b": [["100", "1"]], "a": [["102", "1"]]}]
            for packet in packets:
                await socket.send(json.dumps({"data": packet}))
            await socket.wait_closed()

        monkeypatch.setenv("NO_PROXY", "127.0.0.1")
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr("app.market.engine.WS_ROOT", f"ws://127.0.0.1:{port}")
            engine.bootstrap = AsyncMock()
            engine.task = asyncio.create_task(engine.run())
            try:
                async with asyncio.timeout(3):
                    while not engine.snapshot()["connected"]:
                        await asyncio.sleep(.01)
                assert engine.snapshot()["symbols"][0]["price"] == "101"
            finally:
                await engine.stop()

    asyncio.run(run())
