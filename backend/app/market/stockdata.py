"""DB-backed scorecard / ranking / stock list (shared by API and worker)."""

import json
import math
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.market import details as svc
from app.market import fairvalue as fvm
from app.market.fundamentals import load_series
from app.market.scores import compute_metrics, profile_scores, ranking

FINANCIAL_SECTORS = {"financial services", "financials", "banks", "insurance"}


def _jsonable(v: Any) -> Any:
    if isinstance(v, float) and math.isinf(v):
        return "inf"
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


async def default_strategy(engine: AsyncEngine) -> dict[str, Any]:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT id, name, targets, weights, updated_at FROM ranking_strategy "
                        "WHERE is_default LIMIT 1"
                    )
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return {"id": None, "name": "-", "targets": {}, "weights": {}}
    return {**dict(row), "updated_at": row["updated_at"].isoformat()}


async def _closes(conn: Any, iid: int) -> list[tuple[date, float]]:
    rows = await conn.execute(
        text(
            "SELECT (ts AT TIME ZONE 'UTC')::date AS d, close FROM price_bar_1d "
            "WHERE instrument_id = :iid ORDER BY ts"
        ),
        {"iid": iid},
    )
    return [(r.d, float(r.close)) for r in rows]


async def _period_ends(conn: Any, iid: int) -> dict[int, date]:
    rows = await conn.execute(
        text(
            "SELECT fiscal_year, max(period_end) AS pe FROM fundamental_fact WHERE instrument_id = :iid "
            "AND metric IN ('eps_diluted', 'revenue', 'operating_cf') GROUP BY fiscal_year"
        ),
        {"iid": iid},
    )
    return {r.fiscal_year: r.pe for r in rows}


async def fv_settings(engine: AsyncEngine, iid: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text("SELECT period, overrides FROM fair_value_setting WHERE instrument_id = :iid"),
                    {"iid": iid},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return {"period": fvm.DEFAULT_PERIOD, "overrides": {}}
    return {"period": row["period"], "overrides": dict(row["overrides"])}


async def save_fv_settings(engine: AsyncEngine, iid: int, period: str, overrides: dict[str, float]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("""
            INSERT INTO fair_value_setting (instrument_id, period, overrides, updated_at)
            VALUES (:iid, :p, CAST(:o AS jsonb), now())
            ON CONFLICT (instrument_id) DO UPDATE SET
              period = EXCLUDED.period, overrides = EXCLUDED.overrides, updated_at = now()
        """),
            {"iid": iid, "p": period, "o": json.dumps(overrides)},
        )


async def fair_value(
    engine: AsyncEngine,
    iid: int,
    period: str | None = None,
    series: dict[str, dict[int, float]] | None = None,
    closes: list[tuple[date, float]] | None = None,
) -> dict[str, Any]:
    """Standard fair value with the stored per-stock settings (period may be overridden for viewing)."""
    settings = await fv_settings(engine, iid)
    series = series if series is not None else await load_series(engine, iid)
    async with engine.connect() as conn:
        ends = await _period_ends(conn, iid)
        if closes is None:
            closes = await _closes(conn, iid)
    out = fvm.fair_value(
        series,
        ends,
        closes,
        datetime.now(UTC).date(),
        period or settings["period"],
        fvm.clean_overrides(settings["overrides"]),
    )
    out["saved_period"] = settings["period"]
    out["available"] = bool(series.get("eps_diluted"))
    return out


FV_SUMMARY_KEYS = ("price", "fv_std", "upside", "buy_limit", "expected_return", "period", "bands")


async def fair_value_summary(engine: AsyncEngine, iid: int) -> dict[str, Any]:
    """Small payload for the chart widget (no price history / tables)."""
    series = await load_series(engine, iid)
    if not series.get("eps_diluted"):
        return {"available": False}
    fv = await fair_value(engine, iid, series=series)
    return {"available": fv["fv_std"] is not None, **{k: fv[k] for k in FV_SUMMARY_KEYS}}


async def scorecard(engine: AsyncEngine, iid: int, strategy: dict[str, Any] | None = None) -> dict[str, Any]:
    series = await load_series(engine, iid)
    async with engine.connect() as conn:
        all_closes = await _closes(conn, iid)
        sector = await conn.scalar(
            text("SELECT sector FROM instrument_profile WHERE instrument_id = :iid"), {"iid": iid}
        )
        run = (
            (
                await conn.execute(
                    text(
                        "SELECT source, status, facts, error, finished_at FROM fundamentals_run "
                        "WHERE instrument_id = :iid"
                    ),
                    {"iid": iid},
                )
            )
            .mappings()
            .first()
        )
    closes = [c for _, c in all_closes[-200:]]
    fv = (
        await fair_value(engine, iid, series=series, closes=all_closes) if series.get("eps_diluted") else None
    )
    price = closes[-1] if closes else None
    sma200 = sum(closes) / len(closes) if len(closes) == 200 else None
    is_fin = (sector or "").strip().lower() in FINANCIAL_SECTORS
    m = compute_metrics(
        series,
        price,
        sma200,
        fv_std=fv["fv_std"] if fv else None,
        median_pe=fv["multiples"]["pe"] if fv else None,
        is_financial=is_fin,
    )
    strat = strategy or await default_strategy(engine)
    out: dict[str, Any] = _jsonable(
        {
            "price": price,
            "metrics": asdict(m),
            "profiles": profile_scores(m) if series.get("eps_diluted") else None,
            "ranking": ranking(m, strat["targets"], strat["weights"]) if series.get("eps_diluted") else None,
            "strategy": {"id": strat["id"], "name": strat["name"]},
            "fair_value": {k: fv[k] for k in ("fv_std", "upside", "expected_return", "buy_limit", "period")}
            if fv
            else None,
            "fundamentals": {k: [[y, v] for y, v in sorted(s.items())] for k, s in series.items()},
            "run": {**dict(run), "finished_at": run["finished_at"].isoformat()} if run else None,
        }
    )
    return out


async def store_snapshot(engine: AsyncEngine, iid: int) -> bool:
    card = await scorecard(engine, iid)
    if not card["profiles"]:
        return False
    p = card["profiles"]
    async with engine.begin() as conn:
        await conn.execute(
            text("""
            INSERT INTO score_snapshot (instrument_id, as_of, dividend_yield_score, dividend_growth_score,
                                        earnings_growth_score, ranking_points, detail, computed_at)
            VALUES (:iid, CURRENT_DATE, :a, :b, :c, :r, CAST(:d AS jsonb), now())
            ON CONFLICT (instrument_id, as_of) DO UPDATE SET
              dividend_yield_score = EXCLUDED.dividend_yield_score,
              dividend_growth_score = EXCLUDED.dividend_growth_score,
              earnings_growth_score = EXCLUDED.earnings_growth_score,
              ranking_points = EXCLUDED.ranking_points, detail = EXCLUDED.detail, computed_at = now()
        """),
            {
                "iid": iid,
                "a": p["dividend_yield"]["score"],
                "b": p["dividend_growth"]["score"],
                "c": p["earnings_growth"]["score"],
                "r": card["ranking"]["points"],
                "d": json.dumps({"metrics": card["metrics"], "profiles": p}),
            },
        )
    return True


async def stock_list(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        insts = (
            (
                await conn.execute(
                    text("""
            SELECT DISTINCT i.id, i.symbol, i.name, i.currency, i.country, p.industry, p.sector, p.market_cap
            FROM instrument i JOIN watchlist_item w ON w.instrument_id = i.id
            LEFT JOIN instrument_profile p ON p.instrument_id = i.id
            WHERE i.type = 'stock' AND i.is_active ORDER BY i.symbol""")
                )
            )
            .mappings()
            .all()
        )
    strat = await default_strategy(engine)
    out = []
    for inst in insts:
        card = await scorecard(engine, inst["id"], strat)
        async with engine.connect() as conn:
            st = await svc.stats(conn, inst["id"])
        m, p = card["metrics"], card["profiles"]
        out.append(
            {
                **dict(inst),
                "price": card["price"],
                "scores": {
                    k: (p[k]["score"] if p else None)
                    for k in ("dividend_yield", "dividend_growth", "earnings_growth")
                },
                "ranking_points": card["ranking"]["points"] if card["ranking"] else None,
                "dividend_yield": m["dividend_yield"],
                "dividend_cagr_5y": m["dividend_cagr_5y"],
                "dividend_not_cut_years": m["dividend_not_cut_years"],
                "earnings_stability": m["earnings_stability"],
                "earnings_growth_5y": m["earnings_growth_5y"],
                "payback_years": m["payback_years"],
                "fair_value": m["fair_value"],
                "discount": m["discount"],
                "fv_upside": card["fair_value"]["upside"] if card["fair_value"] else None,
                "expected_return": card["fair_value"]["expected_return"] if card["fair_value"] else None,
                "performance_5y": (st.get("performance") or {}).get("5Y") if st else None,
                "fundamentals": card["run"]["status"] if card["run"] else None,
            }
        )
    return out
