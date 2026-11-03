import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.db import Database, now

TESTNET_URL = "https://testnet.binancefuture.com"


class ExchangeError(Exception):
    pass


class TestnetClient:
    """Manual integration harness, never accessible to LLM/web order routes.

    Endpoints checked against Binance official SDK commit
    13fda514bb2a4358712d849aa3163a0505d96da0. Actual Testnet support must
    be established by authenticated integration tests, not offline mocks.
    """
    def __init__(self, database, api_key, secret, enabled=False, client=None):
        self.database, self.api_key, self.secret, self.enabled = database, api_key, secret, enabled
        self.client = client or httpx.AsyncClient(base_url=TESTNET_URL, timeout=15, follow_redirects=False)
        if str(self.client.base_url).rstrip("/") != TESTNET_URL:
            raise ValueError("Only official Futures Testnet host is allowed")
        self.offset = 0
        with database.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS testnet_intents(id TEXT PRIMARY KEY, created_at TEXT, state TEXT, payload TEXT, result TEXT)")

    async def request(self, method, path, params=None, signed=True):
        values = dict(params or {})
        headers = {}
        if signed:
            if not self.api_key or not self.secret:
                raise ExchangeError("Testnet credentials missing")
            values.update(timestamp=int(time.time() * 1000) + self.offset, recvWindow=5000)
            signature = hmac.new(self.secret.encode(), urlencode(values).encode(), hashlib.sha256).hexdigest()
            values["signature"] = signature
            headers["X-MBX-APIKEY"] = self.api_key
        try:
            response = await self.client.request(method, path, params=values, headers=headers)
        except httpx.HTTPError:
            raise ExchangeError("Testnet transport failed; submission state may be unknown") from None
        if response.status_code >= 300:
            raise ExchangeError(f"Testnet HTTP {response.status_code}; no automatic order retry")
        try:
            return response.json()
        except ValueError:
            raise ExchangeError("Invalid Testnet response") from None

    async def synchronize(self):
        clock = await self.request("GET", "/fapi/v1/time", signed=False)
        self.offset = int(clock["serverTime"]) - int(time.time() * 1000)
        mode = await self.request("GET", "/fapi/v1/positionSide/dual")
        positions = await self.request("GET", "/fapi/v3/positionRisk")
        orders = await self.request("GET", "/fapi/v1/openOrders")
        return {"hedge_mode": mode["dualSidePosition"], "positions": positions, "orders": orders}

    async def submit(self, client_id, params, algo=False):
        if not self.enabled:
            raise PermissionError("Testnet mutations require explicit manual enablement")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", client_id):
            raise ValueError("Invalid client order ID")
        payload = dict(params)
        if payload.get("symbol") is None:
            raise ValueError("Symbol required")
        payload["clientAlgoId" if algo else "newClientOrderId"] = client_id
        key = ("algo:" if algo else "order:") + client_id
        serialized = json.dumps(payload, sort_keys=True)
        with self.database.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            prior = con.execute("SELECT state,payload,result FROM testnet_intents WHERE id=?", (key,)).fetchone()
            if prior:
                if prior["payload"] != serialized:
                    raise ValueError("Order ID reused for different parameters")
                if prior["state"] == "ACK":
                    return json.loads(prior["result"])
                raise ExchangeError("Unresolved intent: reconcile before any further submission")
            con.execute("INSERT INTO testnet_intents VALUES(?,?, 'PENDING', ?, NULL)", (key, now(), serialized))
        try:
            result = await self.request("POST", "/fapi/v1/algoOrder" if algo else "/fapi/v1/order", payload)
        except BaseException:
            with self.database.connect() as con:
                con.execute("UPDATE testnet_intents SET state='UNKNOWN' WHERE id=?", (key,))
            self.database.halt()
            raise
        with self.database.connect() as con:
            con.execute("UPDATE testnet_intents SET state='ACK',result=? WHERE id=?", (json.dumps(result), key))
        return result

    async def reconcile(self, symbol, client_id, algo=False):
        params = {"symbol": symbol, "clientAlgoId" if algo else "origClientOrderId": client_id}
        result = await self.request("GET", "/fapi/v1/algoOrder" if algo else "/fapi/v1/order", params)
        key = ("algo:" if algo else "order:") + client_id
        with self.database.connect() as con:
            con.execute("UPDATE testnet_intents SET state='ACK',result=? WHERE id=?", (json.dumps(result), key))
        return result

    async def cancel(self, symbol, client_id, algo=False):
        if not self.enabled:
            raise PermissionError("Testnet mutations disabled")
        return await self.request("DELETE", "/fapi/v1/algoOrder" if algo else "/fapi/v1/order",
                                  {"symbol": symbol, "clientAlgoId" if algo else "origClientOrderId": client_id})

    async def modify_limit(self, symbol, order_id, side, quantity, price):
        if not self.enabled:
            raise PermissionError("Testnet mutations disabled")
        return await self.request("PUT", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id,
                                  "side": side, "quantity": str(quantity), "price": str(price)})

    @staticmethod
    def protective_params(symbol, position_side, stop, target, hedge):
        if position_side not in {"LONG", "SHORT"}:
            raise ValueError("Position side must be LONG or SHORT")
        side = "SELL" if position_side == "LONG" else "BUY"
        common = {"algoType": "CONDITIONAL", "symbol": symbol, "side": side,
                  "positionSide": position_side if hedge else "BOTH", "closePosition": "true",
                  "workingType": "MARK_PRICE"}
        # closePosition cannot be mixed with quantity/reduceOnly, including Hedge Mode.
        return [{**common, "type": "STOP_MARKET", "triggerPrice": str(stop)},
                {**common, "type": "TAKE_PROFIT_MARKET", "triggerPrice": str(target)}]

    async def close(self):
        await self.client.aclose()


async def probe():
    # Names/presence are inspected; credential values are never printed.
    key, secret = os.environ.get("BINANCE_TESTNET_API_KEY", ""), os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    if not key or not secret:
        print(json.dumps({"verified": False, "reason": "Testnet credentials absent; no request or order sent"}))
        return 1
    settings = Settings()
    database = Database(settings.database_path)
    database.initialize()
    client = TestnetClient(database, key, secret)
    try:
        result = await client.synchronize()
        print(json.dumps({"authenticated_read_verified": True, "hedge_mode": result["hedge_mode"],
                          "position_records": len(result["positions"]), "order_records": len(result["orders"]),
                          "orders_sent": 0, "execution_certified": False}))
        return 0
    except ExchangeError as exc:
        print(json.dumps({"verified": False, "reason": str(exc)}))
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    argparse.ArgumentParser(description="Read-only authenticated Futures Testnet probe").parse_args()
    raise SystemExit(asyncio.run(probe()))
