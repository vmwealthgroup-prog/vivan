from __future__ import annotations
import secrets
import warnings
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "sqlite:///./vmalgo_dev.db"

    JWT_SECRET_KEY: str = secrets.token_urlsafe(48)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    COOKIE_SECURE: bool = True
    COOKIE_DOMAIN: str | None = None
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # Webhook — set to a random 32+ char string in .env
    WEBHOOK_SECRET: str = ""

    # Master gate — cannot be changed via API, requires server restart
    PAPER_TRADING: bool = True

    # Risk limits
    MAX_DAILY_LOSS_PCT: float = 2.0
    MAX_DAILY_TRADES: int = 10
    MAX_RISK_PER_TRADE_PCT: float = 1.0
    MAX_TOTAL_EXPOSURE_PCT: float = 50.0

    # Broker credentials — leave blank until Phase 3
    KOTAK_NEO_API_KEY: str = ""
    KOTAK_NEO_API_SECRET: str = ""
    KOTAK_NEO_CONSUMER_KEY: str = ""


settings = Settings()

if settings.DATABASE_URL.startswith("sqlite") and settings.ENVIRONMENT != "test":
    warnings.warn(
        "DATABASE_URL not set — using SQLite. Set DATABASE_URL to PostgreSQL in production.",
        stacklevel=2,
    )

if not settings.WEBHOOK_SECRET and settings.ENVIRONMENT != "test":
    import logging
    logging.getLogger(__name__).error(
        "WEBHOOK_SECRET is not set — all /webhook/tradingview calls will be rejected. "
        "Set WEBHOOK_SECRET to a 32+ char random string in backend/.env"
    )
