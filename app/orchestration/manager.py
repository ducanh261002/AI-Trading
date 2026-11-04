import asyncio
from contextlib import suppress
from dataclasses import asdict
from uuid import uuid4

from app.agents import AGENTS
from app.market.models import INTERVALS
from app.orchestration.llm import LocalSummary
from app.orchestration.lock import WorkerLock
from app.orchestration.store import TaskStore
from app.orchestration.tools import PLAN, Tools
from app.orchestration.brief import research_brief


class Coordinator:
    def __init__(self, settings, database, market, trading=None):
        self.settings, self.database, self.market = settings, database, market
        self.store = TaskStore(database)
        self.summary = LocalSummary(settings)
        self.tools = Tools(settings, database, market, self.store, self.summary, trading)
        self.lock = WorkerLock(settings.database_path)
        self.worker = None
        self.scheduler = None
        self.running = False
        self.trading = trading
        self.research_enabled = False
        self.research_interval = "5m"
        self.research_message = "CEO chưa được bật tự phân tích."
        self.research_offset = 0

    async def start(self):
        self.store.initialize(default_enabled=bool(self.settings.agent_auto_seconds))
        if self.settings.observer_mode:
            self.store.activate_observer_profile()
        preferences = self.store.research_settings()
        self.research_enabled = bool(preferences["enabled"])
        self.research_interval = preferences["interval"]
        if not self.settings.agents_enabled:
            return
        self.lock.acquire()
        try:
            self.store.recover()
            self.running = True
            self.worker = asyncio.create_task(self.work(), name="agent-worker")
            self.scheduler = asyncio.create_task(self.schedule(), name="agent-scheduler")
        except BaseException:
            self.lock.release()
            raise

    async def stop(self):
        self.running = False
        try:
            for process in (self.scheduler, self.worker):
                if process:
                    process.cancel()
                    with suppress(asyncio.CancelledError):
                        await process
        finally:
            try:
                await self.tools.drain()
            finally:
                self.lock.release()

    def submit(self, symbol, interval, request_key=None, analysis_only=True, candles=None):
        if not self.running or self.worker is None or self.worker.done():
            raise RuntimeError("Agent worker offline")
        if symbol not in self.market.symbols or interval not in INTERVALS:
            raise ValueError("Unsupported symbol or interval")
        candles = self.market.store.read(symbol, interval) if candles is None else candles
        run_id, created = self.store.enqueue(symbol, interval, request_key or str(uuid4()), PLAN,
                                           analysis_only=bool(analysis_only or self.settings.observer_mode), candles=candles)
        return {"run_id": run_id, "created": created}

    async def schedule(self):
        while True:
            try:
                self.research_tick()
            except Exception:
                self.research_message = "CEO gặp lỗi khi lên lịch; xem nhật ký và thử lại. Không mở lệnh."
            await asyncio.sleep(max(5, self.settings.agent_auto_seconds))

    def configure_research(self, enabled, interval):
        if not self.running or self.worker is None or self.worker.done():
            raise RuntimeError("Agent worker chưa sẵn sàng.")
        if interval not in INTERVALS:
            raise ValueError("Khung thời gian không được hỗ trợ.")
        self.store.save_research_settings(enabled, interval)
        self.research_enabled, self.research_interval = enabled, interval
        self.research_message = "CEO đã được bật; đang kiểm tra dữ liệu." if enabled else "Đã dừng xếp nhiệm vụ mới; chu kỳ đang xử lý có thể hoàn tất."
        if enabled:
            self.research_tick()
        return self.research_status()

    def research_tick(self):
        if not self.research_enabled:
            return
        if not self.market.snapshot()["connected"]:
            self.research_message = "Đang chờ dữ liệu LIVE; chưa chạy backtest mới."
            return
        symbols = self.market.symbols
        ordered = symbols[self.research_offset:] + symbols[:self.research_offset]
        self.research_offset = (self.research_offset + 1) % len(symbols)
        messages = []
        for symbol in ordered:
            interval = self.research_interval
            rows = self.market.store.read(symbol, interval)
            if len(rows) < 120:
                messages.append(f"{symbol}: chờ đủ 120 nến đã đóng ({len(rows)}/120).")
                continue
            if self.store.active(symbol, interval):
                messages.append(f"{symbol}: các Agent đang xử lý.")
                continue
            key = "research-" + self.trading.research_fingerprint(rows, symbol, interval)[:48]
            try:
                result = self.submit(symbol, interval, key, analysis_only=True, candles=rows)
                messages.append(f"{symbol}: đã giao 16 nhiệm vụ." if result["created"] else f"{symbol}: chờ nến đóng mới.")
            except OverflowError:
                messages.append("Hàng đợi đang đầy; tự thử lại ở lượt sau.")
        self.research_message = " ".join(messages)

    def research_status(self):
        reports, seen = [], set()
        for item in self.store.runs():
            key = item["symbol"], item["interval"]
            if not item["finished_at"] or not item["analysis_only"] or key in seen:
                continue
            seen.add(key)
            run = self.store.run(item["id"])
            task = next((t for t in run["tasks"] if t["agent_id"] == "report"), {})
            brief = (task.get("result") or {}).get("brief")
            if brief is None:
                brief = research_brief(run, self.store.candles(item["id"]) or [])
            reports.append({**brief, "finished_at": item["finished_at"]})
            if len(reports) >= 5:
                break
        return {"enabled": self.research_enabled, "interval": self.research_interval,
                "symbols": self.market.symbols, "message": self.research_message,
                "worker_running": self.running and self.worker is not None and not self.worker.done(),
                "execution_allowed": False, "reports": reports}

    async def work(self):
        while True:
            self.store.settle()
            task = self.store.claim()
            if task is None:
                await asyncio.sleep(0.1)
                continue
            try:
                if task["agent_id"] == "ceo" and self.settings.ollama_enabled:
                    self.store.transition(task["id"], "Thinking")
                async with asyncio.timeout(self.settings.agent_task_timeout):
                    output = await self.tools.dispatch(task)
                self.store.transition(task["id"], output["status"], result=output["result"])
            except asyncio.CancelledError:
                status = "Pending" if task["attempts"] < task["max_attempts"] else "Error"
                self.store.transition(task["id"], status, error="Worker stopped; read-only task interrupted")
                raise
            except TimeoutError:
                status = "Pending" if task["attempts"] < task["max_attempts"] else "Error"
                self.store.transition(task["id"], status, error="Task timeout")
            except Exception:
                # Never persist arbitrary exception messages, credentials or
                # model response bodies; deterministic errors aren't retried.
                self.store.transition(task["id"], "Error", error="Agent tool failed or permission denied")
            await asyncio.sleep(0)

    def registry(self):
        latest = self.store.latest_agents()
        live = self.running and self.worker is not None and not self.worker.done()
        result = []
        for agent in AGENTS:
            task = latest.get(agent.id)
            state = "Idle" if live else "Offline"
            if live and task:
                state = {"Pending": "Waiting", "Completed": "Idle", "Cancelled": "Idle"}.get(task["status"], task["status"])
            result.append({**asdict(agent), "status": state, "implemented": True,
                           "scope": "Paper trading and analysis; exchange execution disabled",
                           "latest_task": task})
        return result
