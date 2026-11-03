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

    async def start(self):
        self.store.initialize()
        if not self.settings.agents_enabled:
            return
        self.lock.acquire()
        try:
            self.store.recover()
            self.running = True
            self.worker = asyncio.create_task(self.work(), name="agent-worker")
            if self.settings.agent_auto_seconds:
                self.scheduler = asyncio.create_task(self.schedule(), name="agent-scheduler")
        except BaseException:
            self.lock.release()
            raise

    async def stop(self):
        self.running = False
        for process in (self.scheduler, self.worker):
            if process:
                process.cancel()
                with suppress(asyncio.CancelledError):
                    await process
        self.lock.release()

    def submit(self, symbol, interval, request_key=None):
        if not self.running or self.worker is None or self.worker.done():
            raise RuntimeError("Agent worker offline")
        if symbol not in self.market.symbols or interval not in INTERVALS:
            raise ValueError("Unsupported symbol or interval")
        run_id, created = self.store.enqueue(symbol, interval, request_key or str(uuid4()), PLAN)
        return {"run_id": run_id, "created": created}

    async def schedule(self):
        offset = 0
        while True:
            await asyncio.sleep(self.settings.agent_auto_seconds)
            symbols = self.market.symbols
            ordered = symbols[offset:] + symbols[:offset]
            offset = (offset + 1) % len(symbols)
            for symbol in ordered:
                try:
                    self.submit(symbol, "5m")
                except (OverflowError, RuntimeError):
                    break

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
