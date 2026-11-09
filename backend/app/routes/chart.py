from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.deps import CurrentUser, get_engine
from app.market.indicators import divergences, ema, rsi, sma

router = APIRouter(prefix="/api/instruments", tags=["chart"])

BAR_TABLES = {"1d": "price_bar_1d", "1w": "price_bar_1w"}
MAX_PERIODS = 6


def _periods(raw: str | None, name: str) -> list[int]:
    if not raw:
        return []
    try:
        vals = sorted({int(x) for x in raw.split(",") if x.strip()})
    except ValueError as exc:
        raise HTTPException(422, f"{name}: integers expected") from exc
    if len(vals) > MAX_PERIODS or any(not 2 <= v <= 500 for v in vals):
        raise HTTPException(422, f"{name}: max {MAX_PERIODS} periods in 2..500")
    return vals


def _points(ts: list[int], series: list[float | None], start: int) -> list[list[float]]:
    return [[ts[i], round(v, 6)] for i, v in enumerate(series) if i >= start and v is not None]


async def _instrument(conn: AsyncConnection, iid: int) -> dict[str, object]:
    row = (
        (
            await conn.execute(
                text("SELECT id, symbol, name, type, currency FROM instrument WHERE id = :iid"), {"iid": iid}
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instrument not found")
    return dict(row)


@router.get("/{instrument_id}/chart")
async def chart(
    instrument_id: int,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    tf: Annotated[Literal["1d", "1w"], Query()] = "1d",
    limit: Annotated[int, Query(ge=10, le=10000)] = 3000,
    sma_p: Annotated[str | None, Query(alias="sma", max_length=40)] = "20,50,200",
    ema_p: Annotated[str | None, Query(alias="ema", max_length=40)] = "21",
    rsi_p: Annotated[int, Query(alias="rsi", ge=0, le=100)] = 14,
) -> dict[str, object]:
    """Bars + indicators. Indicators are computed with extra warm-up history, then cut to `limit`."""
    smas, emas = _periods(sma_p, "sma"), _periods(ema_p, "ema")
    warmup = max([*smas, *emas, rsi_p * 10, 0])  # Wilder RSI converges after ~10x period
    table = BAR_TABLES[tf]
    async with engine.connect() as conn:
        inst = await _instrument(conn, instrument_id)
        rows = (
            await conn.execute(
                text(f"""
                SELECT ts, open, high, low, close, volume FROM (
                    SELECT ts, open, high, low, close, volume FROM {table}
                    WHERE instrument_id = :iid ORDER BY ts DESC LIMIT :n
                ) s ORDER BY ts
                """),  # noqa: S608 - table from whitelist
                {"iid": instrument_id, "n": limit + warmup},
            )
        ).all()
        levels = (
            (
                await conn.execute(
                    text(
                        "SELECT id, price, color, label FROM chart_level "
                        "WHERE instrument_id = :iid ORDER BY price"
                    ),
                    {"iid": instrument_id},
                )
            )
            .mappings()
            .all()
        )

    ts = [int(r.ts.timestamp()) for r in rows]
    closes = [r.close for r in rows]
    lows = [r.low for r in rows]
    highs = [r.high for r in rows]
    start = max(0, len(rows) - limit)

    indicators: dict[str, list[list[float]]] = {}
    for p in smas:
        indicators[f"sma{p}"] = _points(ts, sma(closes, p), start)
    for p in emas:
        indicators[f"ema{p}"] = _points(ts, ema(closes, p), start)

    rsi_out: dict[str, object] | None = None
    if rsi_p:
        r = rsi(closes, rsi_p)
        divs = [d for d in divergences(lows, highs, r) if d.index >= start]
        rsi_out = {
            "period": rsi_p,
            "values": _points(ts, r, start),
            "divergences": [
                {
                    "t": ts[d.index],
                    "prev_t": ts[d.prev_index],
                    "kind": d.kind,
                    "rsi": round(r[d.index] or 0, 2),
                    "prev_rsi": round(r[d.prev_index] or 0, 2),
                    "price": lows[d.index] if d.kind == "bull" else highs[d.index],
                    "prev_price": lows[d.prev_index] if d.kind == "bull" else highs[d.prev_index],
                }
                for d in divs
            ],
        }

    return {
        "instrument": inst,
        "tf": tf,
        "columns": ["t", "o", "h", "l", "c", "v"],
        "bars": [[ts[i], r.open, r.high, r.low, r.close, r.volume] for i, r in enumerate(rows) if i >= start],
        "indicators": indicators,
        "rsi": rsi_out,
        "levels": [dict(lv) for lv in levels],
    }


class LevelIn(BaseModel):
    price: float = Field(gt=0, lt=1e12)
    color: str = Field(default="#3fb950", pattern=r"^#[0-9a-fA-F]{6}$")
    label: str = Field(default="", max_length=40)


@router.post("/{instrument_id}/levels", status_code=status.HTTP_201_CREATED)
async def add_level(
    instrument_id: int, body: LevelIn, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    async with engine.begin() as conn:
        await _instrument(conn, instrument_id)
        count = await conn.scalar(
            text("SELECT count(*) FROM chart_level WHERE instrument_id = :iid"), {"iid": instrument_id}
        )
        if count is not None and count >= 50:
            raise HTTPException(status.HTTP_409_CONFLICT, "max 50 levels per instrument")
        lid = await conn.scalar(
            text(
                "INSERT INTO chart_level (instrument_id, price, color, label) VALUES (:iid, :p, :c, :l) "
                "RETURNING id"
            ),
            {"iid": instrument_id, "p": body.price, "c": body.color, "l": body.label},
        )
    return {"id": lid, **body.model_dump()}


@router.delete("/{instrument_id}/levels/{level_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_level(
    instrument_id: int, level_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> None:
    async with engine.begin() as conn:
        res = await conn.execute(
            text("DELETE FROM chart_level WHERE id = :id AND instrument_id = :iid"),
            {"id": level_id, "iid": instrument_id},
        )
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "level not found")
