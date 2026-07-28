from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

_url = settings.database_url
_connect_args: dict[str, object] = {}

if settings.POSTGRES_SSL:
    _connect_args["ssl"] = settings.POSTGRES_SSL

if settings.DB_DISABLE_PREPARED_CACHE:
    # Two caches have to go, and they are configured in different places:
    # asyncpg's own is a connect arg, while the one SQLAlchemy's asyncpg
    # dialect keeps on top of it is only readable as a URL query parameter
    # (create_engine() rejects it as a keyword). Leaving either in place still
    # trips "prepared statement already exists" behind a transaction pooler.
    _connect_args["statement_cache_size"] = 0
    _url += ("&" if "?" in _url else "?") + "prepared_statement_cache_size=0"

engine = create_async_engine(
    _url,
    echo=False,
    future=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session
