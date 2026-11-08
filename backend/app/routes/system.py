import secrets
import time
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import CurrentUser, get_engine, get_redis

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/selfcheck")
async def selfcheck(
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> dict[str, object]:
    """End-to-end check: API -> Redis queue -> worker -> DB write -> API DB read."""
    nonce = secrets.token_hex(8)
    start = time.perf_counter()
    job = await redis.enqueue_job("ping", nonce)
    if job is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "enqueue failed")
    try:
        result = await job.result(timeout=15)
    except TimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "worker timeout") from exc
    async with engine.connect() as conn:
        found = await conn.scalar(text("SELECT count(*) FROM system_check WHERE nonce = :n"), {"n": nonce})
    ok = result == nonce and found == 1
    if not ok:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "selfcheck mismatch")
    return {
        "worker": "ok",
        "db_write": "ok",
        "db_read": "ok",
        "latency_ms": round((time.perf_counter() - start) * 1000),
    }
