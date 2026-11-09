from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from arq.connections import ArqRedis
from arq.jobs import Job
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import CurrentUser, get_engine, get_redis
from app.market import alerts as svc
from app.redis_conn import TELEGRAM_STATUS_KEY

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

Kind = Literal[
    "price_above",
    "price_below",
    "change_pct",
    "ma_cross_above",
    "ma_cross_below",
    "rsi_above",
    "rsi_below",
    "fv_upside_above",
]


class AlertIn(BaseModel):
    instrument_id: int = Field(gt=0)
    kind: Kind
    params: dict[str, Any] = Field(default_factory=dict, max_length=5)
    note: str = Field(default="", max_length=200)
    cooldown_minutes: int = Field(default=1440, ge=0, le=43200)
    notify_telegram: bool = True
    is_active: bool = True


async def _validated(engine: AsyncEngine, body: AlertIn) -> dict[str, Any]:
    async with engine.connect() as conn:
        itype = await conn.scalar(
            text("SELECT type FROM instrument WHERE id = :iid"), {"iid": body.instrument_id}
        )
    if itype is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instrument not found")
    if body.kind in svc.STOCK_ONLY and itype != "stock":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "fair value alerts are only available for stocks"
        )
    try:
        params = svc.validate(body.kind, body.params)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {**body.model_dump(), "params": params, "note": " ".join(body.note.split())}


async def _evaluate_soon(redis: ArqRedis, iid: int) -> None:
    await redis.enqueue_job("alerts", iid)


@router.get("")
async def list_alerts(
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
    instrument_id: Annotated[int | None, Query(gt=0)] = None,
) -> dict[str, object]:
    tg = await redis.get(TELEGRAM_STATUS_KEY)
    return {
        "alerts": await svc.list_rules(engine, instrument_id),
        "kinds": svc.KIND_LABEL,
        "telegram": tg.decode() if isinstance(tg, bytes) else tg or "unknown",
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertIn,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> dict[str, Any]:
    data = await _validated(engine, body)
    try:
        rid = await svc.create_rule(engine, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await _evaluate_soon(redis, body.instrument_id)
    rule = await svc.get_rule(engine, rid)
    assert rule is not None
    return rule


@router.put("/{alert_id}")
async def update_alert(
    alert_id: int,
    body: AlertIn,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> dict[str, Any]:
    current = await svc.get_rule(engine, alert_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    if current["instrument_id"] != body.instrument_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "instrument cannot be changed")
    await svc.update_rule(engine, alert_id, await _validated(engine, body))
    await _evaluate_soon(redis, body.instrument_id)
    rule = await svc.get_rule(engine, alert_id)
    assert rule is not None
    return rule


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> None:
    if not await svc.delete_rule(engine, alert_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")


@router.get("/events")
async def list_events(
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    instrument_id: Annotated[int | None, Query(gt=0)] = None,
) -> dict[str, Any]:
    return await svc.events(engine, limit, instrument_id)


@router.post("/events/read")
async def mark_events_read(
    _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, int]:
    return {"marked": await svc.mark_read(engine)}


@router.post("/telegram/test")
async def telegram_test(_user: CurrentUser, redis: Annotated[ArqRedis, Depends(get_redis)]) -> dict[str, str]:
    """Sends a test message via the worker (max. once per minute)."""
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    job: Job | None = await redis.enqueue_job("telegram_test", _job_id=f"tgtest:{minute}")
    if job is None:
        return {"status": "already requested this minute"}
    try:
        result = await job.result(timeout=20)
    except TimeoutError:
        return {"status": "queued (worker busy)"}
    return {"status": str(result)}
