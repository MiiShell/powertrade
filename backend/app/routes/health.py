import logging
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import get_engine, get_redis
from app.redis_conn import WORKER_HEARTBEAT_KEY

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(
    response: Response,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> dict[str, object]:
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            ext = await conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"))
        checks["database"] = "ok" if ext else "fail"
    except Exception:
        log.exception("readiness: database check failed")
        checks["database"] = "fail"
    try:
        await redis.ping()
        checks["redis"] = "ok"
        checks["worker"] = "ok" if await redis.exists(WORKER_HEARTBEAT_KEY) else "fail"
    except Exception:
        log.exception("readiness: redis check failed")
        checks["redis"] = checks["worker"] = "fail"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "degraded", "checks": checks}
