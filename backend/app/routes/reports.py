import re
from typing import Annotated, Literal

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import CurrentUser, get_engine, get_redis
from app.market import chart_analysis as budget
from app.market import reports as svc
from app.market.report_agent import REPORT_COST_CAP_USD
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["reports"])


class ReportIn(BaseModel):
    model: Literal["claude-opus-5-5", "claude-sonnet-5-5"] = "claude-opus-5-5"


@router.post("/instruments/{instrument_id}/reports", status_code=status.HTTP_202_ACCEPTED)
async def start_report(
    instrument_id: int,
    body: ReportIn,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    try:
        rid = await svc.create(
            engine, instrument_id, body.model, settings.ai_monthly_budget_usd, settings.ai_report_daily_limit
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except budget.BudgetError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await redis.enqueue_job("report", rid, _job_id=f"report:{rid}")
    return {"id": rid, "status": "queued"}


@router.get("/reports")
async def list_reports(
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    instrument_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    return {
        "reports": await svc.history(engine, instrument_id, limit),
        "cost_cap_usd": REPORT_COST_CAP_USD,
        "daily_limit": settings.ai_report_daily_limit,
    }


async def _get(engine: AsyncEngine, report_id: int) -> dict[str, object]:
    rep = await svc.get(engine, report_id)
    if rep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return rep


@router.get("/reports/{report_id}")
async def get_report(
    report_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    return await _get(engine, report_id)


@router.get("/reports/{report_id}/markdown")
async def report_markdown(
    report_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> Response:
    rep = await _get(engine, report_id)
    if rep["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "report not finished")
    symbol = re.sub(r"[^A-Za-z0-9.-]", "_", str(rep["symbol"]))
    name = f"powertrade-{symbol}-v{rep['version']}.md"
    return Response(
        svc.to_markdown(rep),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
