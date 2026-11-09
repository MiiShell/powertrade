from typing import Annotated, Literal

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import CurrentUser, get_engine, get_redis
from app.market import ai
from app.market import chart_analysis as svc
from app.redis_conn import AI_STATUS_KEY
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["analysis"])

Model = Literal["claude-opus-5-5", "claude-sonnet-5-5"]


class AnalysisIn(BaseModel):
    tf: Literal["1d", "1w"] = "1d"
    model: Model = "claude-opus-5-5"
    image: str = Field(min_length=100, max_length=ai.MAX_PNG_BYTES * 4 // 3 + 64)  # base64 PNG


@router.get("/ai/usage")
async def ai_usage(
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    st = await redis.get(AI_STATUS_KEY)
    return {
        **await svc.usage(engine, settings.ai_monthly_budget_usd, settings.ai_daily_limit),
        "analyzer": st.decode() if isinstance(st, bytes) else st or "unknown",
    }


@router.post("/instruments/{instrument_id}/analysis", status_code=status.HTTP_202_ACCEPTED)
async def start_analysis(
    instrument_id: int,
    body: AnalysisIn,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    try:
        png = ai.decode_png(body.image)
    except ai.ImageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    try:
        aid = await svc.create(
            engine,
            instrument_id,
            body.tf,
            body.model,
            settings.ai_monthly_budget_usd,
            settings.ai_daily_limit,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except svc.BudgetError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await redis.set(svc.PNG_KEY.format(aid), png, ex=svc.PNG_TTL_S)
    await redis.enqueue_job("chart_analysis", aid, _job_id=f"analysis:{aid}")
    return {"id": aid, "status": "queued"}


@router.get("/analyses/{analysis_id}")
async def get_analysis(
    analysis_id: int,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    context: bool = False,
) -> dict[str, object]:
    a = await svc.get(engine, analysis_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis not found")
    if not context:
        a.pop("context", None)
    return a


@router.get("/instruments/{instrument_id}/analyses")
async def list_analyses(
    instrument_id: int,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    return {"analyses": await svc.history(engine, instrument_id, limit)}
