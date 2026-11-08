"""ARQ worker: background jobs (ingestion, alerts, reports in later phases)."""

from typing import Any, ClassVar

from arq import cron
from sqlalchemy import text

from app.db import create_engine
from app.redis_conn import WORKER_HEARTBEAT_KEY, redis_settings
from app.settings import get_settings

_settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    ctx["engine"] = create_engine(_settings)
    await heartbeat(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


async def heartbeat(ctx: dict[str, Any]) -> None:
    await ctx["redis"].set(WORKER_HEARTBEAT_KEY, "1", ex=30)


async def ping(ctx: dict[str, Any], nonce: str) -> str:
    async with ctx["engine"].begin() as conn:
        await conn.execute(text("INSERT INTO system_check (nonce) VALUES (:n)"), {"n": nonce})
    return nonce


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    cron_jobs: ClassVar[list[Any]] = [cron(heartbeat, second={0, 10, 20, 30, 40, 50}, run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings(_settings)
    health_check_interval = 20
    max_jobs = 10
    job_timeout = 300
