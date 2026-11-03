import asyncio
import time

import httpx

REST_URL = "https://fapi.binance.com"


class MarketAccessError(Exception):
    """Remote destination rejected access; no alternate host bypass."""


class BinanceREST:
    def __init__(self, client=None):
        self.client = client or httpx.AsyncClient(base_url=REST_URL, timeout=15)
        self.used_weight = None
        self.cooldown_until = 0.0

    async def get(self, path, **params):
        for attempt in range(4):
            await asyncio.sleep(max(0, self.cooldown_until - time.monotonic()))
            response = await self.client.get(path, params=params)
            self.used_weight = response.headers.get("x-mbx-used-weight-1m")
            if response.status_code in {403, 451}:
                raise MarketAccessError(f"Market access denied (HTTP {response.status_code})")
            if response.status_code in {418, 429}:
                try:
                    wait = max(1, float(response.headers.get("retry-after", 60)))
                except ValueError:
                    wait = 60
                self.cooldown_until = time.monotonic() + wait
                if attempt == 3:
                    response.raise_for_status()
                continue
            response.raise_for_status()
            # Serialize REST bootstrapping and avoid bursts even below the limit.
            await asyncio.sleep(0.12)
            return response.json()
        raise RuntimeError("REST retry exhausted")

    async def close(self):
        await self.client.aclose()
