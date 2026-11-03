import asyncio
import json
import random
import time
from collections import deque
from contextlib import suppress

from websockets.asyncio.client import connect

from app.market.models import INTERVALS, candle, levels, number
from app.market.rest import BinanceREST, MarketAccessError
from app.market.store import CandleStore
from app.db import now

WS_ROOT = "wss://fstream.binance.com"


class MarketEngine:
    def __init__(self, settings, database, rest=None):
        self.settings = settings
        self.database = database
        self.symbols = settings.market_symbols.split(",")
        self.store = CandleStore(database, settings.candle_limit)
        self.rest = rest or BinanceREST()
        self.task = None
        self.state = "disabled" if not settings.market_enabled else "starting"
        self.error = None
        self.reconnects = 0
        self.metadata = {}
        self.channels = {"market": False, "public": False}
        self.data = {s: {"price": None, "trades": deque(maxlen=50), "book": None,
                         "current": {}, "received": {}, "event_times": {}} for s in self.symbols}

    async def start(self):
        self.store.initialize()
        if self.settings.market_enabled:
            self.task = asyncio.create_task(self.run(), name="binance-market")

    def log(self, level, message):
        with self.database.connect() as con:
            con.execute("INSERT INTO events(task_id,created_at,level,message) VALUES(NULL,?,?,?)",
                        (now(), level, message))

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        await self.rest.close()
        self.channels = dict.fromkeys(self.channels, False)
        self.state = "stopped"

    def urls(self):
        market, public = [], []
        for symbol in self.symbols:
            s = symbol.lower()
            market.extend([f"{s}@aggTrade", *(f"{s}@kline_{i}" for i in INTERVALS)])
            public.append(f"{s}@depth20@500ms")
        return {"market": f"{WS_ROOT}/market/stream?streams={'/'.join(market)}",
                "public": f"{WS_ROOT}/public/stream?streams={'/'.join(public)}"}

    async def bootstrap(self):
        info = await self.rest.get("/fapi/v1/exchangeInfo")
        metadata = {s["symbol"]: s for s in info["symbols"]}
        for symbol in self.symbols:
            spec = metadata.get(symbol, {})
            if spec.get("status") != "TRADING" or spec.get("quoteAsset") != "USDT" or spec.get("contractType") != "PERPETUAL":
                raise MarketAccessError(f"Unsupported trading symbol: {symbol}")
            self.metadata[symbol] = {"filters": spec["filters"], "contract_type": spec["contractType"]}
        server = await self.rest.get("/fapi/v1/time")
        timestamp = int(server["serverTime"])
        self.clock_offset_ms = timestamp - int(time.time() * 1000)
        for symbol in self.symbols:
            self.data[symbol]["current"].clear()
            for interval in INTERVALS:
                rows = await self.rest.get("/fapi/v1/klines", symbol=symbol, interval=interval,
                                           limit=self.settings.candle_limit)
                parsed = [candle(row) for row in rows if int(row[6]) < timestamp]
                self.check_candles(parsed, interval)
                if timestamp - parsed[-1]["close_time"] > INTERVALS[interval] + 60_000:
                    raise ValueError("Stale historical candle window")
                # Replace the retained window after reconnect; historical rows
                # outside it cannot conceal a discontinuity in the active window.
                self.store.save(symbol, interval, parsed)

    @staticmethod
    def check_candles(rows, interval):
        step = INTERVALS[interval]
        if not rows:
            raise ValueError("Empty closed candle history")
        if any(b["open_time"] - a["open_time"] != step for a, b in zip(rows, rows[1:])):
            raise ValueError("Historical candle gap")

    async def run(self):
        attempt = 0
        while True:
            try:
                self.state = "syncing"
                self.log("INFO", "Market data synchronizing from Binance public REST")
                self.channels = dict.fromkeys(self.channels, False)
                for item in self.data.values():
                    item["received"].clear()
                    item["event_times"].clear()
                    item["book"] = None
                await self.bootstrap()
                self.error = None
                async with asyncio.TaskGroup() as group:
                    for channel, url in self.urls().items():
                        group.create_task(self.consume(channel, url))
                    group.create_task(self.watchdog())
                raise RuntimeError("Market streams stopped")
            except asyncio.CancelledError:
                raise
            except MarketAccessError as exc:
                self.error = str(exc)
                self.state = "blocked"
                self.log("WARNING", self.error)
                return
            except Exception:
                # Do not copy proxy URLs, headers or response bodies into UI/logs.
                self.error = "Market connection or data validation failed; retrying"
                self.state = "reconnecting"
                self.channels = dict.fromkeys(self.channels, False)
                self.reconnects += 1
                self.log("WARNING", self.error)
                attempt = min(attempt + 1, 6)
                await asyncio.sleep(min(60, 2 ** attempt) + random.uniform(0, 1))

    async def watchdog(self):
        await asyncio.sleep(45)
        while True:
            if not self.snapshot()["connected"]:
                raise ConnectionError("Stale market data; resync required")
            await asyncio.sleep(5)

    async def consume(self, channel, url):
        # websockets 15 respects inherited HTTP(S) proxy configuration and TLS.
        async with connect(url, open_timeout=15, ping_interval=20, ping_timeout=20,
                           max_queue=32, max_size=1_000_000) as socket:
            self.channels[channel] = True
            self.state = "streaming"
            started = time.monotonic()
            while time.monotonic() - started < 23 * 3600:
                raw = await asyncio.wait_for(socket.recv(), timeout=30)
                self.handle(json.loads(raw))
            raise ConnectionError("Scheduled stream rotation")

    def handle(self, packet):
        event = packet.get("data", packet)
        symbol = event.get("s")
        if symbol not in self.data or event.get("st", 1) != 1:
            return
        item = self.data[symbol]
        kind = event.get("e")
        timestamp = int(event["E"])
        if timestamp <= 0 or timestamp > int(time.time() * 1000) + 60_000:
            raise ValueError("Invalid exchange timestamp")
        if kind == "aggTrade":
            key = "trade"
            trade_id = int(event["a"])
            if item["trades"] and trade_id <= item["trades"][-1]["id"]:
                return
            price, quantity = number(event["p"], True), number(event["q"], True)
            item["price"] = price
            item["trades"].append({"id": trade_id, "price": price, "quantity": quantity, "time": int(event["T"])})
        elif kind == "depthUpdate":
            key = "book"
            update_id = int(event["u"])
            if item["book"] and update_id <= item["book"]["update_id"]:
                return
            bids, asks = levels(event["b"], True), levels(event["a"], False)
            if not bids or not asks or float(bids[0][0]) >= float(asks[0][0]):
                raise ValueError("Invalid top-20 order book")
            item["book"] = {"bids": bids, "asks": asks, "update_id": update_id,
                            "event_time": timestamp, "type": "partial_top20_snapshot"}
        elif kind == "kline":
            k = event["k"]
            interval = k["i"]
            if interval not in INTERVALS:
                return
            key = "kline_" + interval
            if timestamp < item["event_times"].get(key, 0):
                return
            row = candle([k["t"], k["o"], k["h"], k["l"], k["c"], k["v"], k["T"]])
            if row["open_time"] % INTERVALS[interval] or row["close_time"] != row["open_time"] + INTERVALS[interval] - 1:
                raise ValueError("Invalid candle interval boundary")
            if k["x"]:
                history = self.store.read(symbol, interval)
                if history and row["open_time"] > history[-1]["open_time"] + INTERVALS[interval]:
                    raise ValueError("Closed candle gap; reconnect and backfill")
                self.store.save(symbol, interval, [row])
            item["current"][interval] = {**row, "closed": bool(k["x"])}
        else:
            return
        item["received"][key] = time.monotonic()
        item["event_times"][key] = timestamp

    def snapshot(self):
        rows = []
        keys = ["trade", "book", *("kline_" + i for i in INTERVALS)]
        for symbol, item in self.data.items():
            age = {k: round(time.monotonic() - item["received"][k], 2) if k in item["received"] else None for k in keys}
            event_age = {k: round((time.time() * 1000 + getattr(self, "clock_offset_ms", 0) - item["event_times"][k]) / 1000, 2)
                         if k in item["event_times"] else None for k in keys}
            fresh = all(age[k] is not None and age[k] < self.settings.market_stale_seconds
                        and event_age[k] is not None and -5 <= event_age[k] < self.settings.market_stale_seconds for k in keys)
            rows.append({"symbol": symbol, "price": item["price"], "fresh": fresh,
                         "age_seconds": age, "event_age_seconds": event_age,
                         "book": item["book"], "trades": list(item["trades"]),
                         "current_candles": item["current"], "metadata": self.metadata.get(symbol)})
        connected = all(self.channels.values()) and all(row["fresh"] for row in rows)
        return {"source": "Binance USDⓈ-M production public market data", "state": self.state,
                "connected": connected, "channels": self.channels, "error": self.error,
                "reconnects": self.reconnects, "used_weight_1m": self.rest.used_weight,
                "execution_available": False, "symbols": rows}
