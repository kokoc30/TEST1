# app/db/db.py

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Base

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

_initialized = False
_init_lock = asyncio.Lock()


def _default_sqlite_url() -> str:
    backend_root = Path(__file__).resolve().parents[2]  # .../backend
    db_path = backend_root / "talkbridge.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def _normalize_database_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return _default_sqlite_url()

    # Fly / common env formats -> async driver
    if u.startswith("postgres://"):
        u = u.replace("postgres://", "postgresql+asyncpg://", 1)
    elif u.startswith("postgresql://"):
        u = u.replace("postgresql://", "postgresql+asyncpg://", 1)

    # sqlite sync -> sqlite async
    if u.startswith("sqlite:///") and not u.startswith("sqlite+aiosqlite:///"):
        u = u.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

    return u


def _get_database_url() -> str:
    return _normalize_database_url(
        os.getenv("DATABASE_URL", "") or os.getenv("SQLALCHEMY_DATABASE_URL", "")
    )


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is not None and _sessionmaker is not None:
        return _engine

    database_url = _get_database_url()

    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        future=True,
    )

    # SQLite needs foreign_keys=ON for ON DELETE CASCADE to work
    if database_url.startswith("sqlite+aiosqlite:///"):

        @event.listens_for(_engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.close()
            except Exception:
                pass

    _sessionmaker = async_sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def init_db() -> None:
    global _initialized
    if _initialized:
        return

    async with _init_lock:
        if _initialized:
            return

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        _initialized = True


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # lazy init so you don't have to wire startup events
    await init_db()

    sm = get_sessionmaker()
    async with sm() as session:
        yield session
