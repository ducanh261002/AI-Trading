from collections import Counter
from decimal import Decimal
import asyncio

from app.agents import AGENTS
from app.db import now
from app.market.models import INTERVALS
from app.orchestration.store import TERMINAL
from app.trading.indicators import series
from app.trading.strategies import evaluate, STRATEGIES, choose
from app.news import read_news
from app.orchestration.brief import research_brief

# A fixed dependency graph, never supplied by an LLM or external article.
PLAN = (
    ("monitor", "read_health", ()),
    ("security", "audit", ()),
    ("market", "read_market", ("monitor",)),
    ("technical", "calculate_indicators", ("market",)),
    ("news", "read_news", ()),
    ("data", "validate_data", ("market",)),
    ("backtest", "run_backtest", ("technical", "data")),
    ("strategy", "evaluate_strategies", ("backtest", "news")),
    ("signal", "propose_signal", ("strategy",)),
    ("risk", "approve_or_reject", ("signal", "security")),
    ("execution", "execute_approved", ("risk",)),
    ("portfolio", "read_positions", ("execution",)),
    ("accounting", "record_ledger", ("portfolio",)),
    ("performance", "calculate_metrics", ("accounting",)),
    ("report", "read_reports", ("performance", "backtest")),
    ("ceo", "coordinate", ("report",)),
)


def completed(**result):
    return {"status": "Completed", "result": {"as_of": now(), **result}}


def waiting(reason, **result):
    return {"status": "Waiting", "result": {"as_of": now(), "reason": reason, **result}}


class Tools:
    def __init__(self, settings, database, market, store, summary, trading=None):
        self.settings, self.database, self.market = settings, database, market
        self.store, self.summary = store, summary
        self.trading = trading
        self.background_jobs = set()
        self.agents = {agent.id: agent for agent in AGENTS}
        self.handlers = {
            "read_health": self.health, "audit": self.audit,
            "read_market": self.market_analysis, "calculate_indicators": self.technical,
            "read_news": self.news, "validate_data": self.validate_data,
            "evaluate_strategies": self.strategies, "propose_signal": self.signal,
            "approve_or_reject": self.risk, "execute_approved": self.execution,
            "read_positions": self.portfolio, "record_ledger": self.accounting,
            "calculate_metrics": self.performance, "run_backtest": self.backtest,
            "read_reports": self.report, "coordinate": self.coordinate, "halt": self.halt,
        }

    async def dispatch(self, task):
        agent = self.agents.get(task["agent_id"])
        tool = task["tool"]
        if agent is None or tool not in agent.tools or tool not in self.handlers:
            raise PermissionError("Agent tool permission denied")
        return await self.handlers[tool](task)

    def finish_background_job(self, job):
        self.background_jobs.discard(job)
        if not job.cancelled():
            job.exception()  # Retrieve failures even if the task caller timed out.

    async def drain(self):
        if self.background_jobs:
            await asyncio.gather(*tuple(self.background_jobs), return_exceptions=True)

    def view(self, task):
        snapshot = self.market.snapshot()
        symbol = task["input"]["symbol"]
        row = next(row for row in snapshot["symbols"] if row["symbol"] == symbol)
        return snapshot, row

    def candles(self, task):
        rows = self.store.candles(task["run_id"]) if task.get("run_id") else None
        return self.market.store.read(task["input"]["symbol"], task["input"]["interval"]) if rows is None else rows

    def proposal(self, task):
        rows = self.candles(task)
        result = choose(rows) if self.settings.strategy == "consensus" else evaluate(rows, self.settings.strategy)
        return {**result, **task["input"]}

    async def halt(self, task):
        self.database.halt()
        return completed(halted=True)

    async def health(self, task):
        snapshot = self.market.snapshot()
        if self.settings.market_enabled and not snapshot["connected"]:
            self.database.halt()
        return completed(database=self.database.health(), market_connected=snapshot["connected"],
                         halted=self.database.halted(), execution_available=False)

    async def audit(self, task):
        return completed(mode=self.settings.mode, execution_available=False,
                         risk_mutation_api=False, llm_tool_calls=False,
                         scope="Configuration checks only; not a full security audit")

    async def market_analysis(self, task):
        snapshot, row = self.view(task)
        if not snapshot["connected"] or not row["fresh"]:
            return waiting("Fresh market data unavailable", market_state=snapshot["state"])
        return completed(symbol=row["symbol"], price=row["price"], fresh=True,
                         event_age_seconds=row["event_age_seconds"])

    async def technical(self, task):
        snapshot, row = self.view(task)
        interval = task["input"]["interval"]
        rows = self.candles(task)
        if len(rows) < 20:
            return waiting("At least 20 closed candles required", candle_count=len(rows))
        closes = [Decimal(r["close"]) for r in rows[-20:]]
        metrics = {"sma20": str(sum(closes) / 20), "last_close": str(closes[-1]),
                   "change_20_candles_percent": str((closes[-1] / closes[0] - 1) * 100),
                   "candle_count": len(rows), "last_open_time": rows[-1]["open_time"],
                   "scope": "Basic closed-candle statistics; full RSI/MACD/EMA/BB/ATR in phase 4"}
        if len(rows) >= 60:
            metrics.update(indicators=series(rows), scope="Closed-candle RSI, EMA, MACD, Bollinger and ATR")
        if not snapshot["connected"] or not row["fresh"]:
            return waiting("Cached candle statistics only; market not fresh", **metrics)
        return completed(**metrics)

    async def validate_data(self, task):
        snapshot, row = self.view(task)
        interval = task["input"]["interval"]
        rows = self.candles(task)
        gaps = sum(b["open_time"] - a["open_time"] != INTERVALS[interval] for a, b in zip(rows, rows[1:]))
        result = {"candle_count": len(rows), "gaps": gaps, "market_fresh": row["fresh"] and snapshot["connected"]}
        if not rows or gaps or not result["market_fresh"]:
            return waiting("Data quality gate not satisfied", **result)
        return completed(**result)

    async def news(self, task):
        result = await read_news(self.settings.news_feed_url)
        return completed(**result) if result["available"] else waiting(result["reason"])

    async def strategies(self, task):
        snapshot, row = self.view(task)
        rows = self.candles(task)
        if len(rows) < 60:
            return waiting("At least 60 closed candles needed for strategy warmup", actionable=False)
        return completed(proposals=[evaluate(rows, strategy) for strategy in STRATEGIES],
                         actionable=snapshot["connected"] and row["fresh"], paper_only=True)

    async def signal(self, task):
        snapshot, row = self.view(task)
        if not snapshot["connected"] or not row["fresh"]:
            return completed(signal="HOLD", actionable=False, reason="Market not fresh")
        return completed(**self.proposal(task))

    async def risk(self, task):
        return completed(**self.trading.paper.review(self.proposal(task)),
                         paper_only=True, llm_override_allowed=False)

    async def execution(self, task):
        # There is intentionally no exchange client here. A model response,
        # persisted approval or task payload cannot enable execution.
        if task.get("analysis_only") or self.settings.observer_mode:
            return completed(sent=False, paper=True, analysis_only=True, exchange_order_sent=False,
                             reason="Research cycle cannot open positions, including paper")
        return completed(**self.trading.paper.enter(self.proposal(task)))

    async def portfolio(self, task):
        return completed(**self.trading.paper.portfolio())

    async def accounting(self, task):
        return completed(simulated=True, recent_entries=self.trading.paper.ledger()[:20], history_in_database=True)

    async def performance(self, task):
        result = self.trading.paper.performance()
        result.pop("closed_trades", None)
        return completed(**result)

    async def backtest(self, task):
        rows = self.candles(task)
        if len(rows) < 120:
            return waiting("At least 120 closed candles needed for backtest")
        results = []
        for strategy in STRATEGIES:
            job = asyncio.create_task(asyncio.to_thread(self.trading.backtest, **task["input"], strategy=strategy, rows=rows))
            self.background_jobs.add(job)
            job.add_done_callback(self.finish_background_job)
            result = await asyncio.shield(job)
            result.pop("trades", None)
            result.pop("equity_curve", None)
            results.append(result)
        return completed(results=results)

    def counts(self, task):
        run = self.store.run(task["run_id"])
        other_tasks = [t for t in run["tasks"] if t["id"] != task["id"] and t["status"] in TERMINAL]
        return dict(Counter(t["status"] for t in other_tasks)), [t["id"] for t in other_tasks]

    async def report(self, task):
        counts, ids = self.counts(task)
        brief = research_brief(self.store.run(task["run_id"]), self.candles(task))
        return completed(task_counts=counts, evidence_task_ids=ids,
                         execution_available=False, brief=brief, note="Paper results only; missing sources are Waiting")

    async def coordinate(self, task):
        counts, ids = self.counts(task)
        prose = await self.summary.summarize(counts)
        report = next((t for t in self.store.run(task["run_id"])["tasks"] if t["agent_id"] == "report"), {})
        brief = (report.get("result") or {}).get("brief", {})
        return completed(task_counts=counts, evidence_task_ids=ids, execution_available=False,
                         summary=brief.get("summary", "Chu kỳ kết thúc; chưa có đủ bằng chứng từ Report Agent."),
                         conclusion=brief.get("conclusion", "Chưa đủ bằng chứng để kết luận."), local_model=prose)
