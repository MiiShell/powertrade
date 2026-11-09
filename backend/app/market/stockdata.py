"""DB-backed scorecard / ranking / stock list (shared by API and worker)."""

import json
import math
from dataclasses import asdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.market import details as svc
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


async def scorecard(engine: AsyncEngine, iid: int, strategy: dict[str, Any] | None = None) -> dict[str, Any]:
    series = await load_series(engine, iid)
    async with engine.connect() as conn:
        closes = [
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT close FROM (SELECT ts, close FROM price_bar_1d WHERE instrument_id = :iid "
                    "ORDER BY ts DESC LIMIT 200) s ORDER BY ts"
                ),
                {"iid": iid},
            )
        ]
        fy_close = {
            r.fiscal_year: r.close
            for r in await conn.execute(
                text("""
            SELECT f.fiscal_year, p.close FROM fundamental_fact f
            LEFT JOIN LATERAL (SELECT close FROM price_bar_1d
                               WHERE instrument_id = f.instrument_id AND ts < f.period_end + 1
                               ORDER BY ts DESC LIMIT 1) p ON true
            WHERE f.instrument_id = :iid AND f.metric = 'eps_diluted' AND p.close IS NOT NULL"""),
                {"iid": iid},
            )
        }
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
    price = closes[-1] if closes else None
    sma200 = sum(closes) / len(closes) if len(closes) == 200 else None
    is_fin = (sector or "").strip().lower() in FINANCIAL_SECTORS
    m = compute_metrics(series, price, sma200, fy_close, is_financial=is_fin)
    strat = strategy or await default_strategy(engine)
    out: dict[str, Any] = _jsonable(
        {
            "price": price,
            "metrics": asdict(m),
            "profiles": profile_scores(m) if series.get("eps_diluted") else None,
            "ranking": ranking(m, strat["targets"], strat["weights"]) if series.get("eps_diluted") else None,
            "strategy": {"id": strat["id"], "name": strat["name"]},
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
                "performance_5y": (st.get("performance") or {}).get("5Y") if st else None,
                "fundamentals": card["run"]["status"] if card["run"] else None,
            }
        )
    return out
