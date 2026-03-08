from __future__ import annotations
import asyncpg
import structlog
from ..config import Settings

log = structlog.get_logger(__name__)


async def create_pool(settings: Settings) -> asyncpg.Pool | None:
    """Create asyncpg connection pool. Returns None if DB unavailable."""
    try:
        pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
        log.info("db_pool_created")
        return pool
    except Exception as exc:
        log.warning("db_pool_failed", error=str(exc))
        return None


async def setup_tables(pool: asyncpg.Pool) -> None:
    """Create sync state tables if they don't exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_checkpoints (
                connector TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                last_sync_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (connector, entity_type)
            )
        """)
