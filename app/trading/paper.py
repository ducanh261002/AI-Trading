import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.db import now
from app.trading.backtest import exit_price, funding_charge
from app.trading.risk import RiskManager
from app.market.models import INTERVALS


class PaperBroker:
    def __init__(self, settings, database, market):
        self.settings, self.database, self.market = settings, database, market
        self.risk = RiskManager(settings)

    def initialize(self):
        with self.database.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS paper_account(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paper_positions(id TEXT PRIMARY KEY, symbol TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paper_intents(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paper_ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, kind TEXT NOT NULL, amount REAL NOT NULL, position_id TEXT, strategy TEXT);
                CREATE TABLE IF NOT EXISTS backtest_results(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scheduled_reports(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, period TEXT NOT NULL, payload TEXT NOT NULL);
            """)
            if "cache_key" not in {r["name"] for r in con.execute("PRAGMA table_info(backtest_results)")}:
                con.execute("ALTER TABLE backtest_results ADD COLUMN cache_key TEXT")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS backtest_cache_key ON backtest_results(cache_key)")
            initial = self.settings.paper_initial_balance
            con.execute("INSERT OR IGNORE INTO paper_account VALUES(1,?)", (json.dumps({"cash": initial, "peak_equity": initial,
                         "day_start_equity": initial, "day": self.day()}),))

    @staticmethod
    def day():
        return datetime.now(timezone(timedelta(hours=7))).date().isoformat()

    def portfolio(self, con=None):
        if con is None:
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                return self.portfolio(connection)
        account = json.loads(con.execute("SELECT payload FROM paper_account WHERE id=1").fetchone()[0])
        positions = [json.loads(row[0]) for row in con.execute("SELECT payload FROM paper_positions WHERE status='OPEN'")]
        snapshot = self.market.snapshot()
        prices = {r["symbol"]: r["price"] for r in snapshot["symbols"]}
        unrealized = 0.0
        for position in positions:
            mark = float(prices.get(position["symbol"]) or position["entry"])
            position["mark_price"] = mark
            position["unrealized_pnl"] = (mark - position["entry"]) * position["quantity"] * (1 if position["side"] == "LONG" else -1)
            unrealized += position["unrealized_pnl"]
        equity = account["cash"] + unrealized
        if account["day"] != self.day():
            account.update(day=self.day(), day_start_equity=equity)
        account["peak_equity"] = max(account["peak_equity"], equity)
        used_margin = sum(p["entry"] * p["quantity"] / p["leverage"] for p in positions)
        con.execute("UPDATE paper_account SET payload=? WHERE id=1", (json.dumps(account),))
        return {**account, "balance": account["cash"], "equity": equity, "unrealized_pnl": unrealized,
                "free_margin": max(0, equity - used_margin), "positions": positions,
                "drawdown": 1 - equity / account["peak_equity"] if account["peak_equity"] > 0 else 1,
                "daily_pnl": equity - account["day_start_equity"], "market_connected": snapshot["connected"],
                "simulated": True, "funding_is_assumed": True}

    def review(self, proposal):
        symbol = proposal.get("symbol")
        snapshot = self.market.snapshot()
        row = next((r for r in snapshot["symbols"] if r["symbol"] == symbol), {})
        filters = (row.get("metadata") or {}).get("filters", [])
        sized = dict(proposal)
        if row.get("price") and proposal.get("signal") in {"LONG", "SHORT"}:
            sign = 1 if proposal["signal"] == "LONG" else -1
            sized["entry"] = float(row["price"]) * (1 + sign * self.settings.slippage_rate)
        return self.risk.review(sized, self.portfolio(), filters,
                                snapshot["connected"] and row.get("fresh", False), self.database.halted())

    def enter(self, proposal):
        # Recalculate approval now; never trust an approval from an Agent or LLM.
        review = self.review(proposal)
        if not review["approved"]:
            return {"sent": False, "paper": True, "reasons": review["reasons"]}
        symbol = proposal["symbol"]
        snapshot = self.market.snapshot()
        row = next(r for r in snapshot["symbols"] if r["symbol"] == symbol)
        mark = float(row["price"])
        if abs(mark / float(review["entry"]) - 1) > self.settings.max_entry_deviation:
            return {"sent": False, "paper": True, "reasons": ["Price moved away from signal entry"]}
        # Use an intent derived from candle/strategy identity for durable dedup.
        key = hashlib.sha256(f"{symbol}:{proposal['interval']}:{proposal['candle_time']}:{proposal['strategy']}:{proposal['signal']}".encode()).hexdigest()
        sign = 1 if proposal["signal"] == "LONG" else -1
        fill = mark * (1 + sign * self.settings.slippage_rate)
        if not (float(review["stop"]) < fill < float(review["take_profit"]) if sign == 1 else float(review["take_profit"]) < fill < float(review["stop"])):
            return {"sent": False, "paper": True, "reasons": ["Fill would violate stop geometry"]}
        quantity = float(review["quantity"])
        # Never raise size to compensate for slippage. Recheck realized fill risk.
        cost = fill * (2 * self.settings.fee_rate + 2 * self.settings.slippage_rate + 3 * abs(self.settings.funding_rate))
        if quantity * (abs(fill - float(review["stop"])) + cost) > float(review["risk_budget"]):
            return {"sent": False, "paper": True, "reasons": ["Slippage exceeds sized risk budget"]}
        position = {"id": str(uuid4()), "symbol": symbol, "side": proposal["signal"], "entry": fill,
                    "quantity": quantity, "stop": float(review["stop"]), "take_profit": float(review["take_profit"]),
                    "leverage": review["leverage"], "strategy": proposal["strategy"], "interval": proposal["interval"],
                    "opened_at": int(time.time() * 1000), "last_bar": int(time.time() * 1000),
                    "funding_time": int(time.time() * 1000), "funding_paid": 0.0,
                    "entry_fee": fill * quantity * self.settings.fee_rate}
        with self.database.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM paper_intents WHERE id=?", (key,)).fetchone():
                return {"sent": False, "paper": True, "reasons": ["Duplicate signal intent"]}
            # Only this single-process synchronous transaction mutates portfolio.
            if con.execute("SELECT 1 FROM paper_positions WHERE symbol=? AND status='OPEN'", (symbol,)).fetchone():
                return {"sent": False, "paper": True, "reasons": ["Existing position"]}
            account = json.loads(con.execute("SELECT payload FROM paper_account WHERE id=1").fetchone()[0])
            account["cash"] -= position["entry_fee"]
            con.execute("UPDATE paper_account SET payload=? WHERE id=1", (json.dumps(account),))
            con.execute("INSERT INTO paper_intents VALUES(?,?,?)", (key, now(), json.dumps(proposal)))
            con.execute("INSERT INTO paper_positions VALUES(?,?, 'OPEN', ?)", (position["id"], symbol, json.dumps(position)))
            con.execute("INSERT INTO paper_ledger(created_at,kind,amount,position_id,strategy) VALUES(?,'ENTRY_FEE',?,?,?)",
                        (now(), -position["entry_fee"], position["id"], position["strategy"]))
        return {"sent": True, "paper": True, "position_id": position["id"], "exchange_order_sent": False}

    def update_positions(self):
        with self.database.connect() as con:
            open_rows = con.execute("SELECT payload FROM paper_positions WHERE status='OPEN'").fetchall()
        for record in open_rows:
            position = json.loads(record[0])
            bars = self.market.store.read(position["symbol"], position["interval"])
            relevant = [bar for bar in bars if bar["open_time"] >= position["opened_at"] and bar["close_time"] > position["last_bar"]]
            if relevant and relevant[0]["open_time"] > position["last_bar"] + INTERVALS[position["interval"]]:
                self.database.halt()
                continue
            snapshot = self.market.snapshot()
            live = next((r for r in snapshot["symbols"] if r["symbol"] == position["symbol"]), {})
            if snapshot["connected"] and live.get("fresh") and live.get("price"):
                mark = live["price"]
                timestamp = int(time.time() * 1000)
                bars = [*bars, {"open_time": timestamp, "close_time": timestamp, "open": mark, "high": mark, "low": mark, "close": mark}]
            for bar in bars:
                if bar["close_time"] <= position["last_bar"]:
                    continue
                if bar["open_time"] < position["opened_at"]:
                    # Candle includes pre-entry price path; don't apply it to this position.
                    continue
                funding = funding_charge(position, bar["close_time"], self.settings.funding_rate)
                position["funding_paid"] += funding
                position["funding_time"] = bar["close_time"]
                position["last_bar"] = bar["close_time"]
                exit = exit_price(position, bar)
                with self.database.connect() as con:
                    con.execute("BEGIN IMMEDIATE")
                    account = json.loads(con.execute("SELECT payload FROM paper_account WHERE id=1").fetchone()[0])
                    account["cash"] -= funding
                    if funding:
                        con.execute("INSERT INTO paper_ledger(created_at,kind,amount,position_id,strategy) VALUES(?,'FUNDING',?,?,?)",
                                    (now(), -funding, position["id"], position["strategy"]))
                    if exit:
                        price, reason = exit
                        sign = 1 if position["side"] == "LONG" else -1
                        price *= 1 - sign * self.settings.slippage_rate
                        pnl = (price - position["entry"]) * position["quantity"] * sign
                        fee = price * position["quantity"] * self.settings.fee_rate
                        account["cash"] += pnl - fee
                        position.update(exit_price=price, exit_reason=reason, closed_at=bar["close_time"],
                                        net_pnl=pnl - fee - position["entry_fee"] - position["funding_paid"])
                        con.execute("INSERT INTO paper_ledger(created_at,kind,amount,position_id,strategy) VALUES(?,'REALIZED_PNL',?,?,?)", (now(), pnl, position["id"], position["strategy"]))
                        con.execute("INSERT INTO paper_ledger(created_at,kind,amount,position_id,strategy) VALUES(?,'EXIT_FEE',?,?,?)", (now(), -fee, position["id"], position["strategy"]))
                    con.execute("UPDATE paper_positions SET status=?,payload=? WHERE id=?", ("CLOSED" if exit else "OPEN", json.dumps(position), position["id"]))
                    con.execute("UPDATE paper_account SET payload=? WHERE id=1", (json.dumps(account),))
                if exit:
                    break
        portfolio = self.portfolio()
        if portfolio["daily_pnl"] <= -portfolio["day_start_equity"] * self.settings.daily_loss_limit or portfolio["drawdown"] >= self.settings.max_drawdown:
            if not self.database.halted():
                self.database.halt()

    def ledger(self):
        with self.database.connect() as con:
            return [dict(row) for row in con.execute("SELECT * FROM paper_ledger ORDER BY id DESC LIMIT 500")]

    def performance(self):
        with self.database.connect() as con:
            trades = [json.loads(row[0]) for row in con.execute("SELECT payload FROM paper_positions WHERE status='CLOSED'")]
            agent_stats = [dict(row) for row in con.execute("""SELECT agent_id,COUNT(*) AS tasks,
                SUM(CASE WHEN status='Completed' THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN status='Error' THEN 1 ELSE 0 END) AS errors FROM tasks GROUP BY agent_id""")]
        by_strategy = {}
        for trade in trades:
            item = by_strategy.setdefault(trade["strategy"], {"trades": 0, "net_pnl": 0.0, "wins": 0})
            item["trades"] += 1
            item["net_pnl"] += trade["net_pnl"]
            item["wins"] += trade["net_pnl"] > 0
        return {"simulated": True, "trade_count": len(trades), "by_strategy": by_strategy,
                "by_agent": agent_stats, "agent_attribution": "Operational task metrics, not causal profit attribution",
                "closed_trades": trades[-100:]}
