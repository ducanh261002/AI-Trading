"""Opt-in read-only live market smoke check; no credentials or orders."""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.market.engine import MarketEngine


async def probe(timeout):
    with tempfile.TemporaryDirectory(prefix="atc-market-") as directory:
        settings = Settings(database_path=Path(directory) / "probe.db", market_enabled=True)
        database = Database(settings.database_path)
        database.initialize()
        market = MarketEngine(settings, database)
        await market.start()
        try:
            async with asyncio.timeout(timeout):
                while True:
                    snapshot = market.snapshot()
                    if snapshot["connected"]:
                        result = {"live_market_verified": True, "channels": snapshot["channels"],
                                  "symbols": [{"symbol": row["symbol"], "fresh": row["fresh"],
                                               "closed_5m_candles": len(market.store.read(row["symbol"], "5m")),
                                               "trade_count": len(row["trades"])} for row in snapshot["symbols"]],
                                  "orders_sent": 0}
                        print(json.dumps(result, indent=2))
                        return 0
                    if snapshot["state"] == "blocked":
                        break
                    await asyncio.sleep(0.5)
        except TimeoutError:
            pass
        finally:
            snapshot = market.snapshot()
            await market.stop()
        print(json.dumps({"live_market_verified": False, "state": snapshot["state"],
                          "error": snapshot["error"], "orders_sent": 0}, indent=2))
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=90, choices=range(5, 181), metavar="5..180")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(probe(args.timeout)))


if __name__ == "__main__":
    main()
