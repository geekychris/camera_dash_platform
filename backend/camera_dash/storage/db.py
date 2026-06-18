"""SQLAlchemy async engine + session helpers."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def init_db(dsn: str | None = None) -> None:
    global _engine, _sessionmaker
    if dsn is None:
        dsn = os.environ.get(
            "CAMERA_DASH_DSN",
            "sqlite+aiosqlite:///./data/camera_dash.db",
        )
    # Ensure parent dir exists for sqlite
    if dsn.startswith("sqlite") and ":///" in dsn:
        path = dsn.split(":///", 1)[1]
        if path and not path.startswith(":memory:"):
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    _engine = create_async_engine(dsn, future=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    if _sessionmaker is None:
        await init_db()
    assert _sessionmaker is not None
    async with _sessionmaker() as s:
        yield s
