"""Daily bar ingestion: provider fallback by priority, incremental fetch, idempotent upsert, run log."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.market.bars import Bar, sanitize
from app.market.providers import Provider, ProviderError

log = logging.getLogger(__name__)
OVERLAP_DAYS = 7  # re-fetch recent days to pick up corrections / the still-open candle
BATCH = 1000

UPSERT = text("""
    INSERT INTO price_bar_1d
        (instrument_id, ts, open, high, low, close, adj_close, volume, source, fetched_at)
    VALUES (:iid, :ts, :o, :h, :l, :c, :adj, :v, :src, now())
    ON CONFLICT (instrument_id, ts) DO UPDATE SET
        open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
        adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume, source = EXCLUDED.source,
        fetched_at = EXCLUDED.fetched_at
""")


@dataclass(frozen=True)
class IngestResult:
    instrument_id: int
    status: str
    provider: str | None
    rows: int
    error: str | None = None


async def _upsert(engine: AsyncEngine, iid: int, source: str, bars: list[Bar]) -> None:
    async with engine.begin() as conn:
        for i in range(0, len(bars), BATCH):
            await conn.execute(
                UPSERT,
                [
                    {
                        "iid": iid,
                        "ts": b.ts,
                        "o": b.open,
                        "h": b.high,
                        "l": b.low,
                        "c": b.close,
                        "adj": b.adj_close,
                        "v": b.volume,
                        "src": source,
                    }
                    for b in bars[i : i + BATCH]
                ],
            )


async def ingest_instrument(engine: AsyncEngine, providers: dict[str, Provider], iid: int) -> IngestResult:
    async with engine.begin() as conn:
        sources = (
            await conn.execute(
                text(
                    "SELECT provider, provider_symbol FROM instrument_source "
                    "WHERE instrument_id = :iid ORDER BY priority, provider"
                ),
                {"iid": iid},
            )
        ).all()
        last_ts = await conn.scalar(
            text("SELECT max(ts) FROM price_bar_1d WHERE instrument_id = :iid"), {"iid": iid}
        )
        run_id = await conn.scalar(
            text("INSERT INTO ingestion_run (instrument_id, status) VALUES (:iid, 'running') RETURNING id"),
            {"iid": iid},
        )

    start = (last_ts.date() - timedelta(days=OVERLAP_DAYS)) if last_ts else None
    errors: list[str] = []
    result = IngestResult(iid, "failed", None, 0, "no sources configured")
    for provider_name, symbol in sources:
        provider = providers.get(provider_name)
        if provider is None:
            errors.append(f"{provider_name}: unknown provider")
            continue
        try:
            bars = sanitize(await provider.daily(symbol, start))
        except ProviderError as exc:
            errors.append(str(exc))
            continue
        if not bars:
            errors.append(f"{provider_name}: no data")
            continue
        await _upsert(engine, iid, provider_name, bars)
        result = IngestResult(iid, "success", provider_name, len(bars))
        break
    else:
        if errors:
            result = IngestResult(iid, "failed", None, 0, "; ".join(errors)[:500])

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ingestion_run SET finished_at = now(), status = :s, provider = :p, rows = :r, "
                "error = :e WHERE id = :id"
            ),
            {"s": result.status, "p": result.provider, "r": result.rows, "e": result.error, "id": run_id},
        )
    log.info(
        "ingest instrument=%s status=%s provider=%s rows=%s", iid, result.status, result.provider, result.rows
    )
    return result


async def active_instrument_ids(engine: AsyncEngine) -> list[int]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT DISTINCT i.id FROM instrument i JOIN watchlist_item w ON w.instrument_id = i.id "
                "WHERE i.is_active ORDER BY i.id"
            )
        )
        return [r[0] for r in rows]
