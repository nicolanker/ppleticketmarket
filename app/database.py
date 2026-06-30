"""SQLAlchemy engine, session factory, and base model.

Works with both SQLite (development) and PostgreSQL (production) — the only
SQLite-specific tweak is ``check_same_thread`` for the file-based driver.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    # SQLite forbids sharing a connection across threads by default; FastAPI's
    # threadpool needs this relaxed.
    connect_args = {"check_same_thread": False}

engine = create_engine(config.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def init_db() -> None:
    """Create all tables. Import models first so they register with ``Base``."""
    from . import models, predict_models  # noqa: F401  (registers tables with Base.metadata)

    Base.metadata.create_all(bind=engine)
