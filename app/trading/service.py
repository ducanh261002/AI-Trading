import asyncio
import json
import sqlite3
import threading
import hashlib
from contextlib import suppress
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

from app.db import now
from app.trading.backtest import run_backtest
from app.trading.paper import PaperBroker
from app.trading.telemetry import TradingTelemetry
from app.trading.strategies import STRATEGIES, choose, evaluate


class TradingService:
    def __init__(self, settings, database, market):
        self.settings, self.database, self.market = settings, database, market
        self.paper = PaperBroker(settings, database, market)
        self.autopilot_enabled = False
        self.autopilot_interval = '5m'
        self.autopilot_symbols = list(market.symbols)
        self.autopilot_results = []
        self.autopilot_checked_at = None
        self.on_paper_event = None
        self.last_autopilot_messages = {}
        self.telemetry = TradingTelemetry(self)
        self.task = None
        self.maintenance_task = None
        self.maintenance_lock = threading.Lock()
        self.backtest_lock = threading.Lock()

    async def start(self):
        self.paper.initialize()
        self.telemetry.initialize()
        self.task = asyncio.create_task(self.run(), name="paper-and-reports")

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.maintenance_task:
            with suppress(Exception):
                await self.maintenance_task

    def proposal(self, symbol, interval):
        rows = self.market.store.read(symbol, interval)
        proposal = choose(rows) if self.settings.strategy == "consensus" else evaluate(rows, self.settings.strategy)
        return {**proposal, "symbol": symbol, "interval": interval}

    def research_fingerprint(self, rows, symbol, interval):
        costs = {name: getattr(self.settings, name) for name in ("paper_initial_balance", "fee_rate", "slippage_rate", "funding_rate", "risk_per_trade", "daily_loss_limit", "max_drawdown")}
        raw = json.dumps({"engine": "backtest-v2", "symbol": symbol, "interval": interval, "rows": rows, "costs": costs,
                          "signal_selection": self.settings.strategy}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def backtest(self, symbol, interval, strategy, rows=None):
        rows = self.market.store.read(symbol, interval) if rows is None else rows
        cache_key = self.research_fingerprint(rows, symbol, interval) + ":" + strategy
        with self.backtest_lock:
            with self.database.connect() as con:
                cached = con.execute("SELECT id,payload FROM backtest_results WHERE cache_key=?", (cache_key,)).fetchone()
            if cached:
                return {"id": cached["id"], **json.loads(cached["payload"]), "cached": True}
            result = run_backtest(rows, strategy, self.settings)
            identifier = str(uuid4())
            with self.database.connect() as con:
                con.execute("INSERT INTO backtest_results(id,created_at,symbol,interval,payload,cache_key) VALUES(?,?,?,?,?,?)", (identifier, now(), symbol, interval, json.dumps(result), cache_key))
                con.execute("DELETE FROM backtest_results WHERE rowid NOT IN (SELECT rowid FROM backtest_results ORDER BY rowid DESC LIMIT 100)")
            return {"id": identifier, **result, "cached": False}

    def reports(self):
        with self.database.connect() as con:
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in con.execute("SELECT * FROM scheduled_reports ORDER BY created_at DESC LIMIT 30")]

    def maintenance(self):
        with self.maintenance_lock:
            self._maintenance()

    def _maintenance(self):
        local = datetime.now(timezone(timedelta(hours=7)))
        periods = {"hour": local.strftime("%Y-%m-%dT%H"), "day": local.strftime("%Y-%m-%d"), "week": local.strftime("%G-W%V")}
        for period, key in periods.items():
            identifier = period + ":" + key
            start = local.replace(minute=0, second=0, microsecond=0) if period == "hour" else local.replace(hour=0, minute=0, second=0, microsecond=0)
            if period == "week":
                start -= timedelta(days=start.weekday())
            start_utc = start.astimezone(timezone.utc).isoformat()
            with self.database.connect() as con:
                entries = [dict(row) for row in con.execute("SELECT kind,amount FROM paper_ledger WHERE created_at>=?", (start_utc,))]
            performance = self.paper.performance()
            performance.pop("closed_trades", None)
            summary = {"as_of": now(), "timezone": "Asia/Ho_Chi_Minh", "portfolio": self.paper.portfolio(),
                       "performance": performance, "period": period,
                       "period_start": start_utc, "period_net_cash_change": sum(row["amount"] for row in entries),
                       "period_fees": -sum(row["amount"] for row in entries if row["kind"] in {"ENTRY_FEE", "EXIT_FEE"}),
                       "period_funding_cash_change": sum(row["amount"] for row in entries if row["kind"] == "FUNDING"),
                       "scope": "Running period-to-date paper ledger plus current portfolio snapshot"}
            with self.database.connect() as con:
                con.execute("INSERT INTO scheduled_reports VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET created_at=excluded.created_at,payload=excluded.payload", (identifier, now(), period, json.dumps(summary)))
        backup_dir = self.settings.database_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True, parents=True)
        target = backup_dir / (local.strftime("%Y-%m-%d") + ".sqlite3")
        if not target.exists():
            temporary = target.with_suffix(".tmp")
            with sqlite3.connect(self.settings.database_path) as source, sqlite3.connect(temporary) as destination:
                source.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Backup verification failed")
            temporary.replace(target)
        for old in sorted(backup_dir.glob("*.sqlite3"))[:-7]:
            old.unlink()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with self.database.connect() as con:
            con.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
            con.execute("DELETE FROM tasks WHERE run_id IN (SELECT id FROM agent_runs WHERE finished_at < ?)", (cutoff,))
            con.execute("DELETE FROM agent_run_data WHERE run_id IN (SELECT id FROM agent_runs WHERE finished_at < ?)", (cutoff,))
            con.execute("DELETE FROM agent_runs WHERE finished_at < ?", (cutoff,))
            con.execute("DELETE FROM tasks WHERE run_id IS NULL AND finished_at < ?", (cutoff,))
            con.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (int(datetime.now(timezone.utc).timestamp()),))

    def configure_autopilot(self, enabled, symbols=None, interval='5m'):
        if not enabled:
            self.autopilot_enabled = False
            self.paper.autopilot_allowed = False
            self.database.halt()
            return self.autopilot_status()
        snapshot = self.market.snapshot()
        chosen = symbols or self.market.symbols
        if not snapshot['connected'] or any(not next(r for r in snapshot['symbols'] if r['symbol']==s).get('fresh') for s in chosen):
            raise ValueError('PAPER cần dữ liệu Binance LIVE mới để khởi động')
        portfolio = self.paper.portfolio()
        if portfolio['drawdown'] >= self.settings.max_drawdown or portfolio['daily_pnl'] <= -portfolio['day_start_equity']*self.settings.daily_loss_limit:
            raise ValueError('Giới hạn lỗ/drawdown đã chạm; không khởi động PAPER')
        self.autopilot_symbols = list(chosen)
        self.autopilot_interval = interval
        self.autopilot_enabled = True
        self.paper.autopilot_allowed = True
        with self.database.connect() as con:
            con.execute('UPDATE safety SET halted=0,updated_at=? WHERE id=1',(now(),))
        try:
            self.autopilot_tick()
        except Exception:
            self.autopilot_enabled=False
            self.paper.autopilot_allowed=False
            self.database.halt()
            raise ValueError('Không khởi động được PAPER; đã khóa mở lệnh') from None
        return self.autopilot_status()

    def autopilot_tick(self):
        if not self.autopilot_enabled:
            return
        self.autopilot_checked_at = now()
        if self.database.halted():
            self.autopilot_results = [{'symbol':s,'sent':False,'reasons':['Kill Switch / kiểm soát rủi ro đang chặn']} for s in self.autopilot_symbols]
            return
        results=[]
        for symbol in self.autopilot_symbols:
            proposal=self.proposal(symbol,self.autopilot_interval)
            outcome=self.paper.enter(proposal,autopilot=True)
            row={'symbol':symbol,'signal':proposal.get('signal','HOLD'),'sent':bool(outcome.get('sent')),
                 'reasons':outcome.get('reasons') or ([outcome['reason']] if outcome.get('reason') else [])}
            results.append(row)
            signature=json.dumps(row,sort_keys=True)
            if self.on_paper_event and signature!=self.last_autopilot_messages.get(symbol):
                body=(f"PAPER {symbol}: đã ghi nhận lệnh mô phỏng." if row['sent'] else f"PAPER {symbol}: {row['signal']}; "+'; '.join(row['reasons']))
                self.on_paper_event('execution','portfolio','paper',body)
                self.last_autopilot_messages[symbol]=signature
        self.autopilot_results=results

    def autopilot_status(self):
        return {'enabled':self.autopilot_enabled,'mode':'PAPER','halted':self.database.halted(),
                'symbols':self.autopilot_symbols,'interval':self.autopilot_interval,
                'checked_at':self.autopilot_checked_at,'results':self.autopilot_results,
                'exchange_execution_available':False,
                'restart_policy':'Khởi động lại chương trình sẽ khóa PAPER; bấm khởi động để bật lại.'}

    async def run(self):
        ticks = 0
        while True:
            try:
                if self.settings.market_enabled and not self.market.snapshot()["connected"] and not self.database.halted():
                    self.database.halt()
                self.paper.update_positions()
                self.autopilot_tick()
                self.telemetry.sample()
                if self.settings.paper_auto and not self.settings.observer_mode and not self.database.halted():
                    for symbol in self.market.symbols:
                        self.paper.enter(self.proposal(symbol, "5m"))
                if ticks % 12 == 0:
                    # SQLite backup may take time; do it outside the market event loop.
                    self.maintenance_task = asyncio.create_task(asyncio.to_thread(self.maintenance))
                    await asyncio.shield(self.maintenance_task)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.database.halt()
                with self.database.connect() as con:
                    con.execute("INSERT INTO events(created_at,level,message) VALUES(?,'ERROR','Paper/maintenance error; new entries halted')", (now(),))
            ticks += 1
            await asyncio.sleep(5)
