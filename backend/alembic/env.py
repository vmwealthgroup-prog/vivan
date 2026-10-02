"""
Alembic env.py — wired to VM ALGO's SQLAlchemy models and config.
Run migrations:
    cd backend
    DATABASE_URL=postgresql://user:pass@host/dbname alembic upgrade head
"""
from __future__ import annotations

import os
import sys

# Ensure `app` is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models so their metadata is registered on Base
from app.db import Base  # noqa: F401
import app.auth.models  # noqa: F401 — registers User, RefreshToken, ActionToken

from app.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return settings.DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
