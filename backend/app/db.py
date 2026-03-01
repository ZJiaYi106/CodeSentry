"""Database connection management (PostgreSQL via SQLAlchemy async)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""
    pass


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def get_engine():
    """Lazily create and return the async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.postgres_dsn,
            echo=False,
            pool_size=5,
        )
    return _engine


async def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Lazily create and return an async sessionmaker."""
    global _sessionmaker
    if _sessionmaker is None:
        engine = await get_engine()
        _sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncSession:
    """Yield an async database session (FastAPI dependency)."""
    sm = await get_sessionmaker()
    async with sm() as session:
        yield session


async def init_db():
    """Create all tables (for development / demo use)."""
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
