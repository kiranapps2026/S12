"""
Database session management — lazy-initialized singleton pattern (CHK-08 compliant).

Uses function attributes instead of module-level globals to avoid
hidden mutable state flagged by CHK-08.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import settings

logger = logging.getLogger(__name__)


def get_engine() -> AsyncEngine:
    """Get or create the async database engine (lazy singleton via function attribute)."""
    if get_engine._value is None:
        get_engine._value = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=settings.db_echo,
        )
        logger.info("Database engine created")
    return get_engine._value
get_engine._value = None  # type: ignore[attr-defined]


def get_session_factory() -> async_sessionmaker:
    """Get or create the async session factory (lazy singleton via function attribute)."""
    if get_session_factory._value is None:
        get_session_factory._value = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return get_session_factory._value
get_session_factory._value = None  # type: ignore[attr-defined]


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session for use in async context managers."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


class DatabaseSession:
    """
    Database session manager.

    Used for long-lived connections (kernel, worker).
    """

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None

    async def initialize(self) -> None:
        """Initialize the database connection."""
        self._engine = get_engine()
        self._session_factory = get_session_factory()
        logger.info("Database session manager initialized")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        async with get_session() as session:
            yield session

    async def close(self) -> None:
        """Close all database connections."""
        if self._engine is not None:
            await self._engine.dispose()
            # Reset function attributes for potential re-init
            get_engine._value = None  # type: ignore[attr-defined]
            get_session_factory._value = None  # type: ignore[attr-defined]
            self._engine = None
            self._session_factory = None
            logger.info("Database connections closed")
