import ipaddress
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.config import Settings
from app.db import Database
from app.market.engine import MarketEngine
from app.market.models import INTERVALS
from app.orchestration.manager import Coordinator
from app.trading.service import TradingService
from app.trading.strategies import STRATEGIES
from app.security import Auth
from app.observatory import snapshot


class MarketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(default="BTCUSDT", pattern=r"^[A-Z0-9]{2,16}USDT$")
    interval: Literal["5m", "15m", "1h", "4h"] = "5m"
    request_key: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class CycleRequest(MarketRequest):
    analysis_only: bool = True


class ResearchControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    interval: Literal["5m", "15m", "1h", "4h"] = "5m"


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    database = Database(settings.database_path)
    market = MarketEngine(settings, database)
    trading = TradingService(settings, database, market)
    auth = Auth(settings, database)
    coordinator = Coordinator(settings, database, market, trading)

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        auth.initialize()
        await market.start()
        try:
            await coordinator.start()
            await trading.start()
            yield
        finally:
            try:
                await trading.stop()
                await coordinator.stop()
            finally:
                await market.stop()

    app = FastAPI(title="AI Trading Command Center — Agent Coordination", lifespan=lifespan)
    app.state.database = database
    app.state.market = market
    app.state.coordinator = coordinator
    app.state.trading = trading
    hostnames = [urlsplit(settings.public_origin).hostname] if settings.hosted else ["127.0.0.1", "localhost", "[::1]", "testserver"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hostnames)

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        host = request.client.host if request.client else ""
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "testclient"
        if not local and not settings.hosted:
            return JSONResponse({"detail": "Local access only"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if settings.hosted and origin != settings.public_origin.rstrip("/"):
                return JSONResponse({"detail": "Same-origin request required"}, status_code=403)
            if origin and (urlsplit(origin).netloc != request.headers.get("host") or urlsplit(origin).scheme not in {"http", "https"}):
                return JSONResponse({"detail": "Cross-origin mutation rejected"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site mutation rejected"}, status_code=403)
        denied = auth.guard(request)
        response = denied if denied is not None else await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        if settings.hosted:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok" if database.health() else "error", "phase": 7, "mode": settings.mode}

    @app.get("/api/status")
    async def status():
        return {"phase": 7, "mode": settings.mode, "halted": database.halted(), "execution_available": False,
                "paper_auto": settings.paper_auto and not settings.observer_mode, "observer_mode": settings.observer_mode, "hosted": settings.hosted,
                "market_connected": market.snapshot()["connected"], "llm_connected": False,
                "ollama_enabled": settings.ollama_enabled, "ollama_last_request_ok": coordinator.summary.available,
                "agents_running": coordinator.running and coordinator.worker is not None and not coordinator.worker.done(),
                "risk": {name: getattr(settings, name) for name in ("risk_per_trade", "daily_loss_limit", "max_drawdown", "max_positions", "max_exposure", "max_leverage")}}

    @app.get("/api/observatory")
    async def observatory():
        return snapshot(coordinator, market, settings)

    @app.get("/api/agents")
    async def agents():
        return coordinator.registry()

    @app.post("/api/agent-cycles", status_code=202)
    async def agent_cycle(body: CycleRequest):
        try:
            return coordinator.submit(body.symbol, body.interval, body.request_key, analysis_only=body.analysis_only)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/agent-cycles")
    async def agent_cycles():
        return coordinator.store.runs()

    @app.get("/api/agent-cycles/{run_id}")
    async def agent_cycle_result(run_id: str):
        result = coordinator.store.run(run_id)
        if result is None:
            raise HTTPException(404, "Agent cycle not found")
        return result

    @app.get("/api/research")
    async def research_status():
        return coordinator.research_status()

    @app.post("/api/research")
    async def research_control(body: ResearchControl):
        try:
            return coordinator.configure_research(body.enabled, body.interval)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/market")
    async def market_snapshot():
        return market.snapshot()

    @app.get("/api/candles/{symbol}")
    async def candles(symbol: str, interval: str = "5m"):
        if symbol not in market.symbols or interval not in INTERVALS:
            raise HTTPException(422, "Unsupported symbol or interval")
        rows = market.store.read(symbol, interval)
        return {"symbol": symbol, "interval": interval, "source": "Binance REST/WS closed candles",
                "market_connected": market.snapshot()["connected"], "candles": rows}

    @app.get("/api/tasks")
    def tasks():
        return database.list_rows("tasks")

    @app.get("/api/events")
    def events():
        return database.list_rows("events")

    @app.post("/api/diagnostics", status_code=201)
    def diagnostic():
        return {"task_id": database.diagnostic()}

    @app.post("/api/kill-switch")
    def kill_switch():
        database.halt()
        return {"halted": True, "execution_available": False}

    @app.post("/api/orders")
    def orders():
        raise HTTPException(403, "Exchange execution disabled; paper operations use /api/paper routes")

    @app.get("/api/portfolio")
    async def portfolio():
        return trading.paper.portfolio()

    @app.get("/api/performance")
    async def performance():
        return trading.paper.performance()

    @app.get("/api/ledger")
    async def ledger():
        return trading.paper.ledger()

    @app.get("/api/reports")
    async def reports():
        return trading.reports()

    @app.get("/api/strategies/{symbol}")
    async def strategy_results(symbol: str, interval: str = "5m"):
        if symbol not in market.symbols or interval not in INTERVALS:
            raise HTTPException(422, "Unsupported symbol/interval")
        return trading.proposal(symbol, interval)

    @app.post("/api/backtests")
    async def backtests(body: MarketRequest, strategy: Literal["ema_rsi", "macd_atr", "bollinger_volume"] = "ema_rsi"):
        if body.symbol not in market.symbols:
            raise HTTPException(422, "Unsupported symbol")
        try:
            return await asyncio.to_thread(trading.backtest, body.symbol, body.interval, strategy)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/paper/arm")
    async def arm_paper(body: dict):
        if settings.observer_mode:
            raise HTTPException(409, "Chế độ quan sát không mở vị thế")
        if body != {"confirmation": "ENABLE PAPER ONLY"}:
            raise HTTPException(422, "Explicit paper-only confirmation required")
        if not market.snapshot()["connected"]:
            raise HTTPException(409, "Fresh market data required")
        portfolio = trading.paper.portfolio()
        if portfolio["drawdown"] >= settings.max_drawdown or portfolio["daily_pnl"] <= -portfolio["day_start_equity"] * settings.daily_loss_limit:
            raise HTTPException(409, "Risk limits exceeded; cannot arm")
        with database.connect() as con:
            con.execute("UPDATE safety SET halted=0 WHERE id=1")
        return {"paper_armed": True, "exchange_execution_available": False}

    @app.post("/api/paper/run")
    async def paper_run(body: MarketRequest):
        if settings.observer_mode:
            raise HTTPException(409, "Chế độ quan sát không mở vị thế")
        if body.symbol not in market.symbols:
            raise HTTPException(422, "Unsupported symbol")
        return trading.paper.enter(trading.proposal(body.symbol, body.interval))

    @app.post("/auth/login")
    async def login(request: Request):
        return await auth.login(request)

    @app.post("/auth/logout")
    async def logout(request: Request):
        return auth.logout(request)

    static = Path(__file__).parent / "static"

    @app.get("/login", include_in_schema=False)
    def login_page():
        return FileResponse(static / "login.html")

    @app.get("/login.js", include_in_schema=False)
    def login_script():
        return FileResponse(static / "login.js", media_type="text/javascript")

    @app.get("/scene.js", include_in_schema=False)
    def scene_script():
        return FileResponse(static / "scene.js", media_type="text/javascript")

    @app.get("/vendor/three.module.js", include_in_schema=False)
    def three_module():
        return FileResponse(static / "vendor" / "three.module.js", media_type="text/javascript")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(static / ("index.html" if settings.observer_mode else "operator.html"))

    @app.get("/operator", include_in_schema=False)
    def operator_page():
        return FileResponse(static / "operator.html")

    @app.get("/observer.js", include_in_schema=False)
    def observer_script():
        return FileResponse(static / "observer.js", media_type="text/javascript")

    @app.get("/observer.css", include_in_schema=False)
    def observer_style():
        return FileResponse(static / "observer.css", media_type="text/css")

    @app.get("/dashboard.js", include_in_schema=False)
    def javascript():
        return FileResponse(static / "dashboard.js", media_type="text/javascript")

    @app.get("/style.css", include_in_schema=False)
    def css():
        return FileResponse(static / "style.css", media_type="text/css")

    return app


app = create_app()
