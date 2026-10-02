"""
VM ALGO — Database session management (SQLAlchemy)
=======================================================
Shared by app/auth/ now; any future module that needs persistence (OMS,
PMS audit logs, etc.) uses the same engine/session rather than opening its
own connection — this is the direct fix for the old root-level database.py,
which hardcoded a password AND opened its own psycopg2 connection at
import time (meaning just importing the module tried to connect to a DB).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
