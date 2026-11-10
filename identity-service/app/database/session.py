"""Async engine and session factory.

Tables are never created here: the schema is managed only by Alembic migrations.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            pool_size=s.database_pool_size,
            max_overflow=s.database_max_overflow,
            pool_pre_ping=True,
            echo=s.database_echo,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _factory
    if _factory is None:
        _factory = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """One session per request. Services decide when to commit; anything uncommitted is rolled back."""
    async with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            # A failed request never leaves flushed changes behind.
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine, _factory = None, None
