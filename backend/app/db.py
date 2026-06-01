"""Async database engine and session management."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Set during init_db: True when pgvector extension is present on the server.
pgvector_enabled: bool = False


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def _pgvector_installed() -> bool:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        return row.scalar() is not None


async def _try_enable_pgvector() -> bool:
    """Best-effort pgvector setup; never aborts the caller's transaction."""
    if await _pgvector_installed():
        return True
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        return await _pgvector_installed()
    return await _pgvector_installed()


async def init_db() -> None:
    """Create tables. Enables pgvector when available (optional)."""
    global pgvector_enabled

    import app.models  # noqa: F401

    pgvector_enabled = await _try_enable_pgvector()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
