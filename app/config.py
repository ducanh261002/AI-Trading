from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATC_", env_file=".env", extra="ignore")
    mode: Literal["paper"] = "paper"
    database_path: Path = Path("data/command_center.sqlite3")
    risk_per_trade: float = Field(default=0.005, gt=0, le=0.005)
    daily_loss_limit: float = Field(default=0.02, gt=0, le=0.02)
    max_drawdown: float = Field(default=0.10, gt=0, le=0.10)
    max_positions: int = Field(default=3, ge=1, le=3)
    max_exposure: float = Field(default=1.0, gt=0, le=1.0)
    max_leverage: int = Field(default=2, ge=1, le=2)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    market_enabled: bool = True
    market_symbols: str = "BTCUSDT,ETHUSDT"
    market_stale_seconds: float = Field(default=15, ge=5, le=120)
    candle_limit: int = Field(default=200, ge=50, le=500)
    agents_enabled: bool = True
    agent_task_timeout: float = Field(default=45, ge=1, le=120)
    agent_auto_seconds: int = Field(default=0, ge=0, le=3600)
    ollama_enabled: bool = False
    hosted: bool = False
    public_origin: str = "http://127.0.0.1:8000"
    admin_password_hash: SecretStr = SecretStr("")
    paper_initial_balance: float = Field(default=10000, ge=100, le=10000000)
    fee_rate: float = Field(default=0.0005, ge=0, le=0.01)
    slippage_rate: float = Field(default=0.0002, ge=0, le=0.01)
    funding_rate: float = Field(default=0.0001, ge=-0.01, le=0.01)
    max_entry_deviation: float = Field(default=0.002, gt=0, le=0.01)
    live_watch_seconds: int = Field(default=15, ge=5, le=300)
    observer_mode: bool = True
    paper_auto: bool = False
    strategy: Literal["ema_rsi", "macd_atr", "bollinger_volume", "consensus"] = "consensus"
    news_feed_url: str = ""

    @model_validator(mode="after")
    def cloud_security(self):
        from urllib.parse import urlsplit
        origin = urlsplit(self.public_origin)
        if not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}:
            raise ValueError("Invalid public origin")
        if self.hosted and (origin.scheme != "https" or not self.admin_password_hash.get_secret_value().startswith("scrypt:")):
            raise ValueError("Hosted mode requires HTTPS origin and a scrypt admin password hash")
        return self

    @field_validator("agent_auto_seconds")
    @classmethod
    def validate_auto_interval(cls, value):
        if 0 < value < 30:
            raise ValueError("Automatic cycles require at least 30 seconds")
        return value

    @field_validator("ollama_url")
    @classmethod
    def local_ollama_only(cls, value):
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Ollama must be a local HTTP server")
        return value.rstrip("/")

    @field_validator("market_symbols")
    @classmethod
    def validate_symbols(cls, value):
        import re
        symbols = value.upper().split(",")
        if not 1 <= len(symbols) <= 5 or len(set(symbols)) != len(symbols):
            raise ValueError("Choose 1–5 distinct symbols")
        if any(not re.fullmatch(r"[A-Z0-9]{2,16}USDT", s) for s in symbols):
            raise ValueError("Invalid USDT symbol")
        return ",".join(symbols)
