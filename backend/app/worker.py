"""ARQ worker: background jobs (ingestion now; alerts, reports in later phases)."""

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron
from sqlalchemy import text

from app.db import create_engine
from app.market.details import profiles_due, refresh_profile, store_snapshots
from app.market.factory import fmp_budget
from app.market.ingest import active_instrument_ids, ingest_instrument
from app.market.providers import build_providers
from app.redis_conn import WORKER_HEARTBEAT_KEY, redis_settings
from app.settings import get_settings

_settings = get_settings()
logging.getLogger("httpx").setLevel(logging.WARNING)  # never log request URLs


async def startup(ctx: dict[str, Any]) -> None:
    ctx["engine"] = create_engine(_settings)
    ctx["providers"], ctx["http"] = build_providers(
        _settings.providers_mode,
        _settings.http_user_agent,
        fmp_api_key=_settings.fmp_api_key,
        fmp_budget=fmp_budget(ctx["redis"], _settings),
    )
    await heartbeat(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    if ctx.get("http") is not None:
        await ctx["http"].aclose()
    await ctx["engine"].dispose()


async def heartbeat(ctx: dict[str, Any]) -> None:
    await ctx["redis"].set(WORKER_HEARTBEAT_KEY, "1", ex=30)


async def ping(ctx: dict[str, Any], nonce: str) -> str:
    async with ctx["engine"].begin() as conn:
        await conn.execute(text("INSERT INTO system_check (nonce) VALUES (:n)"), {"n": nonce})
    return nonce


async def ingest(ctx: dict[str, Any], instrument_id: int) -> dict[str, Any]:
    r = await ingest_instrument(ctx["engine"], ctx["providers"], instrument_id)
    snaps = await store_snapshots(ctx["engine"], instrument_id) if r.status == "success" else 0
    return {"status": r.status, "provider": r.provider, "rows": r.rows, "error": r.error, "snapshots": snaps}


async def profile(ctx: dict[str, Any], instrument_id: int) -> str:
    return await refresh_profile(ctx["engine"], ctx["providers"], instrument_id)


async def schedule_ingestion(ctx: dict[str, Any]) -> int:
    """Enqueue one ingest job per watched instrument; job id dedupes within the hour."""
    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    ids = await active_instrument_ids(ctx["engine"])
    for iid in ids:
        await ctx["redis"].enqueue_job("ingest", iid, _job_id=f"ingest:{iid}:{hour}")
    # company profiles: max 5 per hour, refreshed weekly (FMP budget friendly)
    for iid in await profiles_due(ctx["engine"], limit=5):
        await ctx["redis"].enqueue_job("profile", iid, _job_id=f"profile:{iid}:{hour}")
    return len(ids)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, ingest, profile]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, second={0, 10, 20, 30, 40, 50}, run_at_startup=True),
        cron(schedule_ingestion, minute=5, run_at_startup=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings(_settings)
    health_check_interval = 20
    max_jobs = 10
    job_timeout = 300
