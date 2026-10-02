"""
VM ALGO — Settings
=====================
Every secret comes from the environment. Nothing here is hardcoded — this
is the direct fix for the two plaintext database passwords that were
committed to the repo root (main.py, database.py) before this pass.

Dev convenience: if DATABASE_URL is unset, we fall back to a local SQLite
file so `uvicorn app.main:app` works with zero setup for a new contributor.
That fallback is loud (a startup warning), not silent, and production must
set DATABASE_URL to a real PostgreSQL DSN per the spec — see .env.example.
"""

from __future__ import annotations

import secrets
import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "sqlite:///./vmalgo_dev.db"

    # No default secret ships in code — a random one is generated per-process
    # if the env var is missing, which invalidates all tokens on restart.
    # That's intentional: it makes "forgot to set JWT_SECRET_KEY in prod"
    # loudly break auth instead of quietly shipping a guessable default.
    JWT_SECRET_KEY: str = secrets.token_urlsafe(48)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    COOKIE_SECURE: bool = True          # only send cookies over HTTPS — set False for plain-http local dev
    COOKIE_DOMAIN: str | None = None

    FRONTEND_BASE_URL: str = "http://localhost:3000"  # used to build email verification / reset links


settings = Settings()

if settings.DATABASE_URL.startswith("sqlite") and settings.ENVIRONMENT != "test":
    warnings.warn(
        "DATABASE_URL is not set — falling back to a local SQLite file. "
        "This is fine for local dev but the spec requires PostgreSQL in "
        "production. Set DATABASE_URL in your .env (see .env.example).",
        stacklevel=2,
    )
