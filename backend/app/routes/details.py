from datetime import UTC, datetime
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import CurrentUser, get_engine, get_redis
from app.market import details as svc

router = APIRouter(prefix="/api/instruments", tags=["details"])


async def _instrument(engine: AsyncEngine, iid: int) -> dict[str, object]:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT id, symbol, name, type, currency, isin, exchange, country "
                        "FROM instrument WHERE id = :iid"
                    ),
                    {"iid": iid},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instrument not found")
    return dict(row)


@router.get("/{instrument_id}/details")
async def details(
    instrument_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    inst = await _instrument(engine, instrument_id)
    async with engine.connect() as conn:
        return {
            "instrument": inst,
            "profile": await svc.profile(conn, instrument_id),
            "stats": await svc.stats(conn, instrument_id),
            "technicals": {tf: await svc.technicals(conn, instrument_id, tf) for tf in ("1d", "1w", "1mo")},
            "pivots": {tf: await svc.pivots(conn, instrument_id, tf) for tf in ("1d", "1w", "1mo")},
            "rating_history": [
                {"date": r.ts.date().isoformat(), "label": r.summary_label, "score": r.summary_score}
                for r in await conn.execute(
                    text(
                        "SELECT ts, summary_label, summary_score FROM technical_snapshot "
                        "WHERE instrument_id = :iid AND tf = '1d' ORDER BY ts DESC LIMIT 30"
                    ),
                    {"iid": instrument_id},
                )
            ],
        }


@router.get("/{instrument_id}/seasonality")
async def seasonality(
    instrument_id: int,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    from_year: Annotated[int | None, Query(ge=1900, le=2200)] = None,
    to_year: Annotated[int | None, Query(ge=1900, le=2200)] = None,
) -> dict[str, object]:
    await _instrument(engine, instrument_id)
    if from_year and to_year and from_year > to_year:
        raise HTTPException(422, "from_year > to_year")
    async with engine.connect() as conn:
        return await svc.seasonal(conn, instrument_id, from_year, to_year)


@router.post("/{instrument_id}/profile/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_profile(
    instrument_id: int,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> dict[str, str]:
    await _instrument(engine, instrument_id)
    day = datetime.now(UTC).strftime("%Y%m%d")  # max one manual profile call per instrument/day (FMP budget)
    job = await redis.enqueue_job("profile", instrument_id, _job_id=f"profile:{instrument_id}:manual:{day}")
    return {"status": "queued" if job else "already requested today"}


@router.get("/{instrument_id}/stats")
async def stats(
    instrument_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    """Lightweight key stats (price, day/week/52-week range) for the chart widgets."""
    await _instrument(engine, instrument_id)
    async with engine.connect() as conn:
        return await svc.stats(conn, instrument_id)
