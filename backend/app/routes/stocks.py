from datetime import UTC, datetime
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import CurrentUser, get_engine, get_redis
from app.market import stockdata
from app.market.scores import RANKING_CRITERIA

router = APIRouter(prefix="/api", tags=["stocks"])


@router.get("/stocks")
async def stocks(
    _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    return {
        "strategy": (await stockdata.default_strategy(engine))["name"],
        "stocks": await stockdata.stock_list(engine),
    }


async def _exists(engine: AsyncEngine, iid: int) -> None:
    async with engine.connect() as conn:
        if not await conn.scalar(text("SELECT 1 FROM instrument WHERE id = :iid"), {"iid": iid}):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "instrument not found")


@router.get("/instruments/{instrument_id}/scorecard")
async def scorecard(
    instrument_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    await _exists(engine, instrument_id)
    return await stockdata.scorecard(engine, instrument_id)


@router.post("/instruments/{instrument_id}/fundamentals/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh(
    instrument_id: int,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> dict[str, str]:
    await _exists(engine, instrument_id)
    day = datetime.now(UTC).strftime("%Y%m%d")
    job = await redis.enqueue_job("fundamentals", instrument_id, _job_id=f"fund:{instrument_id}:manual:{day}")
    return {"status": "queued" if job else "already requested today"}


class StrategyIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    targets: dict[str, float]
    weights: dict[str, float]

    def validate_keys(self) -> None:
        keys = set(RANKING_CRITERIA)
        if set(self.targets) != keys or set(self.weights) - keys:
            raise HTTPException(422, f"targets must contain exactly: {sorted(keys)}")
        for k, v in self.targets.items():
            if not 0 <= v <= 1000:
                raise HTTPException(422, f"target {k} out of range")
        for k, v in self.weights.items():
            if not 0 <= v <= 10:
                raise HTTPException(422, f"weight {k} must be 0..10")


@router.get("/ranking/strategy")
async def get_strategy(
    _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    return await stockdata.default_strategy(engine)


@router.put("/ranking/strategy")
async def put_strategy(
    body: StrategyIn, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    body.validate_keys()
    import json

    weights = {k: body.weights.get(k, 1.0) for k in RANKING_CRITERIA}
    async with engine.begin() as conn:
        await conn.execute(
            text("""
            UPDATE ranking_strategy SET name = :n, targets = CAST(:t AS jsonb), weights = CAST(:w AS jsonb),
                   updated_at = now() WHERE is_default"""),
            {"n": " ".join(body.name.split()), "t": json.dumps(body.targets), "w": json.dumps(weights)},
        )
    return await stockdata.default_strategy(engine)
