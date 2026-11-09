"""DB-backed detail computations shared by API and worker."""

import json
import logging
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.market.analytics import OHLCV, DayBar, key_stats, pivot_points, seasonality
from app.market.profile import clean_fmp_profile
from app.market.providers import Provider, ProviderError
from app.market.technicals import compute_rating, summarize

log = logging.getLogger(__name__)
TABLES = {"1d": "price_bar_1d", "1w": "price_bar_1w", "1mo": "price_bar_1mo"}  # whitelist


async def load_ohlcv(conn: AsyncConnection, iid: int, tf: str, limit: int) -> list[Any]:
    table = TABLES[tf]
    rows = await conn.execute(
        text(f"""SELECT ts, open, high, low, close, volume FROM (
                 SELECT ts, open, high, low, close, volume FROM {table}
                 WHERE instrument_id = :iid ORDER BY ts DESC LIMIT :n) s ORDER BY ts"""),  # noqa: S608
        {"iid": iid, "n": limit},
    )
    return list(rows)


async def technicals(conn: AsyncConnection, iid: int, tf: str) -> dict[str, Any] | None:
    rows = await load_ohlcv(conn, iid, tf, 400)
    if len(rows) < 2:
        return None
    r = compute_rating(
        [x.open for x in rows],
        [x.high for x in rows],
        [x.low for x in rows],
        [x.close for x in rows],
        [x.volume for x in rows],
    )
    out = summarize(r)
    out["as_of"] = rows[-1].ts.date().isoformat()
    out["bars"] = len(rows)
    return out


async def pivots(conn: AsyncConnection, iid: int, tf: str) -> dict[str, Any] | None:
    """1d -> previous completed month; 1w/1mo -> previous completed year (TradingView 'auto' periods)."""
    months = await load_ohlcv(conn, iid, "1mo", 30)
    now = datetime.now(UTC)
    done = [m for m in months if (m.ts.year, m.ts.month) < (now.year, now.month)]
    if not done:
        return None
    if tf == "1d":
        m = done[-1]
        o, h, lo, c = m.open, m.high, m.low, m.close
        basis = f"Monat {m.ts:%Y-%m}"
    else:
        year = now.year - 1
        ys = [m for m in done if m.ts.year == year]
        if not ys:
            return None
        o, h, lo, c = ys[0].open, max(m.high for m in ys), min(m.low for m in ys), ys[-1].close
        basis = f"Jahr {year}"
    return {"basis": basis, "ohlc": [o, h, lo, c], "levels": pivot_points(o, h, lo, c)}


async def stats(conn: AsyncConnection, iid: int) -> dict[str, Any]:
    rows = await load_ohlcv(conn, iid, "1d", 2000)
    return key_stats([OHLCV(r.ts.date(), r.open, r.high, r.low, r.close, r.volume) for r in rows])


async def seasonal(
    conn: AsyncConnection, iid: int, from_year: int | None, to_year: int | None
) -> dict[str, Any]:
    rows = await conn.execute(
        text("SELECT ts, close FROM price_bar_1d WHERE instrument_id = :iid ORDER BY ts"), {"iid": iid}
    )
    return seasonality([DayBar(r.ts.date(), r.close) for r in rows], from_year, to_year)


async def profile(conn: AsyncConnection, iid: int) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                text("SELECT * FROM instrument_profile WHERE instrument_id = :iid"), {"iid": iid}
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    out = {k: v for k, v in row.items() if k != "instrument_id"}
    out["ipo_date"] = out["ipo_date"].isoformat() if out.get("ipo_date") else None
    out["fetched_at"] = out["fetched_at"].isoformat()
    return out


# ---------- persistence (worker) ----------
async def store_snapshots(engine: AsyncEngine, iid: int) -> int:
    """Persist the current technical rating per timeframe (one row per instrument/tf/bar)."""
    n = 0
    async with engine.begin() as conn:
        for tf in ("1d", "1w", "1mo"):
            t = await technicals(conn, iid, tf)
            if t is None:
                continue
            s = t["summary"]
            await conn.execute(
                text("""
                INSERT INTO technical_snapshot (instrument_id, tf, ts, summary_label, summary_score,
                    oscillators_label, ma_label, counts, rows, computed_at)
                VALUES (:iid, :tf, :ts, :sl, :ss, :ol, :ml, CAST(:counts AS jsonb),
                        CAST(:rows AS jsonb), now())
                ON CONFLICT (instrument_id, tf, ts) DO UPDATE SET
                    summary_label = EXCLUDED.summary_label, summary_score = EXCLUDED.summary_score,
                    oscillators_label = EXCLUDED.oscillators_label, ma_label = EXCLUDED.ma_label,
                    counts = EXCLUDED.counts, rows = EXCLUDED.rows, computed_at = now()
                """),
                {
                    "iid": iid,
                    "tf": tf,
                    "ts": datetime.combine(
                        date.fromisoformat(t["as_of"]), time.min, tzinfo=UTC
                    ),  # asyncpg: timestamptz needs datetime
                    "sl": s["label"],
                    "ss": s["score"],
                    "ol": t["oscillators"]["label"],
                    "ml": t["moving_averages"]["label"],
                    "counts": json.dumps(
                        {
                            "summary": s["counts"],
                            "oscillators": t["oscillators"]["counts"],
                            "moving_averages": t["moving_averages"]["counts"],
                        }
                    ),
                    "rows": json.dumps(
                        {
                            "oscillators": t["oscillators"]["rows"],
                            "moving_averages": t["moving_averages"]["rows"],
                        }
                    ),
                },
            )
            n += 1
    return n


async def refresh_profile(engine: AsyncEngine, providers: dict[str, Provider], iid: int) -> str:
    async with engine.connect() as conn:
        src = (
            await conn.execute(
                text(
                    "SELECT i.type, s.provider_symbol FROM instrument i "
                    "LEFT JOIN instrument_source s ON s.instrument_id = i.id AND s.provider = 'fmp' "
                    "WHERE i.id = :iid"
                ),
                {"iid": iid},
            )
        ).first()
    if src is None or src.provider_symbol is None or src.type not in ("stock", "etf"):
        return "skipped"
    fmp = providers.get("fmp")
    if fmp is None or not hasattr(fmp, "profile_raw"):
        return "skipped"
    try:
        raw = await fmp.profile_raw(src.provider_symbol)
    except ProviderError as exc:
        log.info("profile instrument=%s failed: %s", iid, exc)
        return f"failed: {exc}"
    p = clean_fmp_profile(raw)
    if p is None:
        return "failed: empty profile"
    data = p.as_db()
    cols = list(data)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"""
            INSERT INTO instrument_profile (instrument_id, source, {", ".join(cols)}, fetched_at)
            VALUES (:iid, 'fmp', {", ".join(":" + c for c in cols)}, now())
            ON CONFLICT (instrument_id) DO UPDATE SET source = EXCLUDED.source,
              {", ".join(f"{c} = EXCLUDED.{c}" for c in cols)}, fetched_at = now()
            """),  # noqa: S608 - column names from dataclass fields
            {"iid": iid, **data},
        )
        # enrich instrument master data (only fill gaps; never overwrite a set ISIN)
        await conn.execute(
            text("""
            UPDATE instrument i SET
              name = CASE WHEN i.name = '' OR i.name IS NULL THEN COALESCE(:name, i.name) ELSE i.name END,
              exchange = COALESCE(i.exchange, :exchange),
              country = COALESCE(i.country, :country),
              isin = COALESCE(i.isin, CASE WHEN NOT EXISTS (SELECT 1 FROM instrument x WHERE x.isin = :isin)
                                           THEN :isin END)
            WHERE i.id = :iid
            """),
            {
                "iid": iid,
                "name": p.company_name,
                "exchange": p.exchange,
                "country": p.country,
                "isin": p.isin,
            },
        )
    return "success"


async def profiles_due(engine: AsyncEngine, limit: int = 5) -> list[int]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
            SELECT DISTINCT i.id, p.fetched_at FROM instrument i
            JOIN watchlist_item w ON w.instrument_id = i.id
            JOIN instrument_source s ON s.instrument_id = i.id AND s.provider = 'fmp'
            LEFT JOIN instrument_profile p ON p.instrument_id = i.id
            WHERE i.is_active AND i.type IN ('stock','etf')
              AND (p.fetched_at IS NULL OR p.fetched_at < now() - INTERVAL '7 days')
            ORDER BY p.fetched_at NULLS FIRST LIMIT :n
            """),
            {"n": limit},
        )
        return [r[0] for r in rows]
