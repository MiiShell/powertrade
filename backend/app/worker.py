"""ARQ worker: background jobs (ingestion, fundamentals, profiles, alerts; reports in later phases)."""

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron, func
from sqlalchemy import text

from app.db import create_engine
from app.market import ai
from app.market import alerts as alert_svc
from app.market import chart_analysis as analysis_svc
from app.market.details import profiles_due, refresh_profile, store_snapshots
from app.market.factory import fmp_budget
from app.market.fundamentals import fundamentals_due, refresh_fundamentals
from app.market.ingest import active_instrument_ids, ingest_instrument
from app.market.notify import NotifyError, build_notifier
from app.market.providers import build_providers
from app.market.stockdata import store_snapshot
from app.redis_conn import AI_STATUS_KEY, TELEGRAM_STATUS_KEY, WORKER_HEARTBEAT_KEY, redis_settings
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
        sec_contact=_settings.sec_contact,
    )
    ctx["notifier"] = build_notifier(
        _settings.providers_mode, ctx["http"], _settings.telegram_bot_token, _settings.telegram_chat_id
    )
    status = ctx["notifier"].name if ctx["notifier"].configured else getattr(ctx["notifier"], "reason", "off")
    await ctx["redis"].set(TELEGRAM_STATUS_KEY, status)
    ctx["analyzer"] = ai.build_analyzer(_settings.providers_mode, _settings.anthropic_api_key)
    await ctx["redis"].set(AI_STATUS_KEY, ctx["analyzer"].name)
    await heartbeat(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    if isinstance(ctx.get("analyzer"), ai.AnthropicAnalyzer):
        await ctx["analyzer"].aclose()
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
    fired = 0
    if r.status == "success":
        await store_snapshot(ctx["engine"], instrument_id)  # daily quality-score snapshot (price-dependent)
        fired = await alert_svc.evaluate_instrument(ctx["engine"], ctx["notifier"], instrument_id)
    return {
        "status": r.status,
        "provider": r.provider,
        "rows": r.rows,
        "error": r.error,
        "snapshots": snaps,
        "alerts": fired,
    }


async def alerts(ctx: dict[str, Any], instrument_id: int) -> int:
    """Evaluate one instrument's rules now (after a rule was created/changed)."""
    return await alert_svc.evaluate_instrument(ctx["engine"], ctx["notifier"], instrument_id)


async def chart_analysis(ctx: dict[str, Any], analysis_id: int) -> str:
    return await analysis_svc.run(ctx["engine"], ctx["analyzer"], ctx["redis"], analysis_id)


async def expire_analyses(ctx: dict[str, Any]) -> int:
    return await analysis_svc.expire_stale(ctx["engine"])


async def telegram_test(ctx: dict[str, Any]) -> str:
    n = ctx["notifier"]
    if not n.configured:
        return getattr(n, "reason", "telegram not configured")
    try:
        await n.send("✅ PowerTrade: Telegram-Alerts sind eingerichtet.")
    except NotifyError as exc:
        return str(exc)
    return "sent"


async def fundamentals(ctx: dict[str, Any], instrument_id: int) -> str:
    status = await refresh_fundamentals(ctx["engine"], ctx["providers"], ctx["redis"], instrument_id)
    if status == "success":
        await store_snapshot(ctx["engine"], instrument_id)
    return status


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
    # annual fundamentals: weekly per stock, max 10 per hour
    for iid in await fundamentals_due(ctx["engine"], limit=10):
        await ctx["redis"].enqueue_job("fundamentals", iid, _job_id=f"fund:{iid}:{hour}")
    return len(ids)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        ingest,
        profile,
        fundamentals,
        alerts,
        telegram_test,
        func(chart_analysis, timeout=900, max_tries=1),  # Claude call (streaming, high effort)
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, second={0, 10, 20, 30, 40, 50}, run_at_startup=True),
        cron(schedule_ingestion, minute=5, run_at_startup=True),
        cron(expire_analyses, minute={0, 10, 20, 30, 40, 50}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings(_settings)
    health_check_interval = 20
    max_jobs = 10
    job_timeout = 300
