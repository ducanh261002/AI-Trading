import asyncio
import hashlib
import hmac
from urllib.parse import urlencode

import httpx
import pytest

from app.db import Database
from app.execution.testnet import TestnetClient as Client, TESTNET_URL, ExchangeError


def test_signature_idempotency_and_unknown_reconciliation(tmp_path):
    database = Database(tmp_path / "testnet.db")
    database.initialize()
    calls = []

    def handler(request):
        calls.append(request)
        params = dict(request.url.params)
        signature = params.pop("signature")
        assert hmac.compare_digest(signature, hmac.new(b"test-secret", urlencode(params).encode(), hashlib.sha256).hexdigest())
        if request.method == "POST" and params["newClientOrderId"] == "ambiguous":
            raise httpx.ReadTimeout("never log signed URL")
        return httpx.Response(200, json={"orderId": 123, "status": "NEW"})

    async def run():
        transport = httpx.MockTransport(handler)
        client = Client(database, "test-key", "test-secret", enabled=True,
                        client=httpx.AsyncClient(base_url=TESTNET_URL, transport=transport))
        params = {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "quantity": "0.001", "price": "100", "timeInForce": "GTC"}
        assert (await client.submit("unique", params))["orderId"] == 123
        assert (await client.submit("unique", params))["orderId"] == 123
        assert len(calls) == 1
        with pytest.raises(ExchangeError):
            await client.submit("ambiguous", params)
        assert database.halted()
        with pytest.raises(ExchangeError, match="reconcile"):
            await client.submit("ambiguous", params)
        assert len(calls) == 2
        await client.reconcile("BTCUSDT", "ambiguous")
        assert (await client.submit("ambiguous", params))["orderId"] == 123
        await client.close()

    asyncio.run(run())


def test_protection_params_and_default_disabled(tmp_path):
    for hedge in (False, True):
        for side in ("LONG", "SHORT"):
            params = Client.protective_params("BTCUSDT", side, 90, 120, hedge)
            assert params[0]["type"] == "STOP_MARKET" and params[1]["type"] == "TAKE_PROFIT_MARKET"
            assert all("quantity" not in p and "reduceOnly" not in p for p in params)
            assert params[0]["positionSide"] == (side if hedge else "BOTH")
    database = Database(tmp_path / "db")
    database.initialize()
    async def run():
        client = Client(database, "", "")
        with pytest.raises(PermissionError):
            await client.submit("x", {"symbol": "BTCUSDT"})
        await client.close()
    asyncio.run(run())
