"""PostgreSQL engine and session setup."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from search_anything.settings import Settings, get_settings


def make_engine(settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def make_session_factory(
    settings: Settings | None = None,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(make_engine(settings), expire_on_commit=False)
