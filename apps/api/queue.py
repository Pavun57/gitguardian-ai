"""arq queue helpers — the boundary between the fast-ACK webhook and the worker.

Jobs carry only a scan UUID; all state lives in Postgres / LangGraph checkpoints,
so jobs are tiny and safe to re-enqueue.
"""

from arq.connections import ArqRedis, create_pool

from core.config import get_settings

_pool: ArqRedis | None = None

SCAN_JOB = "run_scan"


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        from urllib.parse import urlparse

        from arq.connections import RedisSettings

        parsed = urlparse(get_settings().redis_url)
        _pool = await create_pool(
            RedisSettings(
                host=parsed.hostname or "localhost",
                port=parsed.port or 6379,
                database=int((parsed.path or "/0").lstrip("/")),
            )
        )
    return _pool


async def enqueue_scan(scan_id: str) -> None:
    pool = await get_pool()
    await pool.enqueue_job(SCAN_JOB, scan_id, _job_id=f"scan:{scan_id}")


async def is_duplicate_delivery(redis, delivery_id: str) -> bool:
    """Dedup webhook deliveries: GitHub retries on non-2xx/timeout."""
    return not await redis.set(f"gh:delivery:{delivery_id}", "1", nx=True, ex=86400)
