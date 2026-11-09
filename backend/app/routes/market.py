from datetime import UTC, date, datetime
from typing import Annotated, Literal

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import CurrentUser, get_engine, get_redis
from app.market.factory import fmp_budget
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["market"])

DEFAULT_WATCHLIST = "Standard"
InstrumentType = Literal["stock", "etf", "index", "crypto", "commodity", "fx"]
ProviderName = Literal["yahoo", "stooq", "kraken", "fmp"]
BAR_TABLES = {"1d": "price_bar_1d", "1w": "price_bar_1w"}  # whitelist -> safe identifier


class SourceIn(BaseModel):
    provider: ProviderName
    symbol: str = Field(pattern=r"^[A-Za-z0-9.\-=^_]{1,32}$")
    priority: int = Field(default=1, ge=1, le=9)


class InstrumentIn(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9.\-=^_]{1,32}$")
    name: str = Field(default="", max_length=120)
    type: InstrumentType
    currency: str = Field(default="USD", pattern=r"^[A-Za-z]{3}$")
    sources: list[SourceIn] | None = Field(default=None, max_length=5)

    @field_validator("symbol", "currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


def default_sources(symbol: str, typ: str, currency: str) -> list[SourceIn]:
    if typ == "crypto":
        kraken_base = "XBT" if symbol == "BTC" else symbol
        return [
            SourceIn(provider="yahoo", symbol=f"{symbol}-{currency}", priority=1),
            SourceIn(provider="kraken", symbol=f"{kraken_base}{currency}", priority=2),
        ]
    sources = [SourceIn(provider="yahoo", symbol=symbol, priority=1)]
    if typ in ("stock", "etf"):
        sources.append(SourceIn(provider="fmp", symbol=symbol, priority=2))
    return sources


@router.get("/watchlist")
async def get_watchlist(
    _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("""
                SELECT i.id, i.symbol, i.name, i.type, i.currency,
                       lb.ts AS last_ts, lb.close AS last_close, pb.close AS prev_close,
                       r.status AS run_status, r.finished_at AS run_at, r.error AS run_error
                FROM watchlist_item w
                JOIN watchlist wl ON wl.id = w.watchlist_id AND wl.name = :wl
                JOIN instrument i ON i.id = w.instrument_id
                LEFT JOIN LATERAL (SELECT ts, close FROM price_bar_1d
                                   WHERE instrument_id = i.id ORDER BY ts DESC LIMIT 1) lb ON true
                LEFT JOIN LATERAL (SELECT close FROM price_bar_1d
                                   WHERE instrument_id = i.id ORDER BY ts DESC OFFSET 1 LIMIT 1) pb ON true
                LEFT JOIN LATERAL (SELECT status, finished_at, error FROM ingestion_run
                                   WHERE instrument_id = i.id ORDER BY started_at DESC LIMIT 1) r ON true
                ORDER BY w.position, i.symbol
                """),
                {"wl": DEFAULT_WATCHLIST},
            )
        ).mappings()
        items = []
        for r in rows:
            change = (
                (r["last_close"] / r["prev_close"] - 1) * 100 if r["last_close"] and r["prev_close"] else None
            )
            items.append(
                {
                    "id": r["id"],
                    "symbol": r["symbol"],
                    "name": r["name"],
                    "type": r["type"],
                    "currency": r["currency"],
                    "last_close": r["last_close"],
                    "last_date": r["last_ts"].date().isoformat() if r["last_ts"] else None,
                    "change_pct": round(change, 2) if change is not None else None,
                    "ingestion": {
                        "status": r["run_status"],
                        "at": r["run_at"].isoformat() if r["run_at"] else None,
                        "error": r["run_error"],
                    },
                }
            )
    return {"name": DEFAULT_WATCHLIST, "items": items}


@router.post("/watchlist/items", status_code=status.HTTP_201_CREATED)
async def add_watchlist_item(
    body: InstrumentIn,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> dict[str, object]:
    sources = body.sources or default_sources(body.symbol, body.type, body.currency)
    async with engine.begin() as conn:
        iid = await conn.scalar(
            text("""
            INSERT INTO instrument (symbol, name, type, currency) VALUES (:s, :n, :t, :c)
            ON CONFLICT (symbol, type) DO UPDATE
            SET name = COALESCE(NULLIF(EXCLUDED.name, ''), instrument.name)
            RETURNING id
            """),
            {"s": body.symbol, "n": body.name, "t": body.type, "c": body.currency},
        )
        for src in sources:
            await conn.execute(
                text("""
                INSERT INTO instrument_source (instrument_id, provider, provider_symbol, priority)
                VALUES (:iid, :p, :ps, :prio)
                ON CONFLICT (instrument_id, provider) DO UPDATE
                SET provider_symbol = EXCLUDED.provider_symbol, priority = EXCLUDED.priority
                """),
                {"iid": iid, "p": src.provider, "ps": src.symbol, "prio": src.priority},
            )
        await conn.execute(
            text("""
            INSERT INTO watchlist_item (watchlist_id, instrument_id, position)
            SELECT wl.id, :iid, COALESCE((SELECT max(position) + 1 FROM watchlist_item
                                         WHERE watchlist_id = wl.id), 0)
            FROM watchlist wl WHERE wl.name = :wl
            ON CONFLICT DO NOTHING
            """),
            {"iid": iid, "wl": DEFAULT_WATCHLIST},
        )
    await redis.enqueue_job("ingest", iid, _job_id=f"ingest:{iid}:add")
    return {"id": iid, "symbol": body.symbol, "sources": [s.model_dump() for s in sources]}


@router.delete("/watchlist/items/{instrument_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_watchlist_item(
    instrument_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> None:
    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                "DELETE FROM watchlist_item USING watchlist wl WHERE watchlist_item.watchlist_id = wl.id "
                "AND wl.name = :wl AND watchlist_item.instrument_id = :iid"
            ),
            {"wl": DEFAULT_WATCHLIST, "iid": instrument_id},
        )
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not in watchlist")


@router.post("/instruments/{instrument_id}/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_instrument(
    instrument_id: int,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> dict[str, str]:
    async with engine.connect() as conn:
        if not await conn.scalar(text("SELECT 1 FROM instrument WHERE id = :iid"), {"iid": instrument_id}):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "instrument not found")
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    job = await redis.enqueue_job("ingest", instrument_id, _job_id=f"ingest:{instrument_id}:manual:{minute}")
    return {"status": "queued" if job else "already queued"}


@router.get("/instruments/{instrument_id}/bars")
async def get_bars(
    instrument_id: int,
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    tf: Annotated[Literal["1d", "1w"], Query()] = "1d",
    start: date | None = None,
    end: date | None = None,
    limit: Annotated[int, Query(ge=1, le=10000)] = 2000,
) -> dict[str, object]:
    table = BAR_TABLES[tf]
    async with engine.connect() as conn:
        inst = (
            (
                await conn.execute(
                    text("SELECT id, symbol, name, type, currency FROM instrument WHERE id = :iid"),
                    {"iid": instrument_id},
                )
            )
            .mappings()
            .first()
        )
        if inst is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "instrument not found")
        rows = await conn.execute(
            text(f"""
            SELECT ts, open, high, low, close, volume FROM (
                SELECT ts, open, high, low, close, volume FROM {table}
                WHERE instrument_id = :iid
                  AND (CAST(:start AS date) IS NULL OR ts >= CAST(:start AS date))
                  AND (CAST(:end AS date) IS NULL OR ts <= CAST(:end AS date))
                ORDER BY ts DESC LIMIT :limit
            ) s ORDER BY ts
            """),  # noqa: S608 - table from whitelist
            {"iid": instrument_id, "start": start, "end": end, "limit": limit},
        )
        bars = [[int(r.ts.timestamp()), r.open, r.high, r.low, r.close, r.volume] for r in rows]
    return {"instrument": dict(inst), "tf": tf, "columns": ["t", "o", "h", "l", "c", "v"], "bars": bars}


@router.get("/ingestion/runs")
async def ingestion_runs(
    _user: CurrentUser,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, object]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("""
                SELECT r.id, i.symbol, r.provider, r.status, r.rows, r.error, r.started_at, r.finished_at
                FROM ingestion_run r JOIN instrument i ON i.id = r.instrument_id
                ORDER BY r.started_at DESC LIMIT :limit
                """),
                {"limit": limit},
            )
        ).mappings()
        runs = [
            {
                **dict(r),
                "started_at": r["started_at"].isoformat(),
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            }
            for r in rows
        ]
    return {"runs": runs}


@router.get("/providers/usage")
async def provider_usage(
    _user: CurrentUser,
    redis: Annotated[ArqRedis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    fmp = await fmp_budget(redis, settings).usage()
    return {"fmp": {**fmp, "configured": bool(settings.fmp_api_key)}}
