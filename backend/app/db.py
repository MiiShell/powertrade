from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.settings import Settings


def create_engine(s: Settings) -> AsyncEngine:
    return create_async_engine(s.app_db_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
