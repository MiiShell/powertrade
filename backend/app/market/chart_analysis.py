"""Claude chart analysis: context from the DB, budget guard, request/result storage.

Flow: API validates the PNG, checks the budget, stores a `queued` row (with the JSON context and a cost
reservation) and puts the image into Redis (short TTL) -> worker job calls Claude, logs usage/cost in
`ai_call_log` and stores the structured result. Numbers sent to Claude come only from the DB.
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.market import ai
from app.market import details as svc
from app.market.indicators import divergences, ema, rsi, sma

BAR_TABLES = {"1d": "price_bar_1d", "1w": "price_bar_1w"}  # whitelist
CONTEXT_BARS = 150
WARMUP = 250
PNG_KEY = "pt:ai:png:{}"
PNG_TTL_S = 900


class BudgetError(Exception):
    pass


def _r(v: float | None, d: int = 4) -> float | None:
    return None if v is None else round(float(v), d)


async def build_context(conn: AsyncConnection, iid: int, tf: str) -> dict[str, Any]:
    inst = (
        (
            await conn.execute(
                text("SELECT id, symbol, name, type, currency FROM instrument WHERE id = :iid"), {"iid": iid}
            )
        )
        .mappings()
        .first()
    )
    if inst is None:
        raise LookupError("instrument not found")
    rows = await svc.load_ohlcv(conn, iid, tf, CONTEXT_BARS + WARMUP)
    if len(rows) < 30:
        raise ValueError("not enough price history for an analysis")
    closes = [r.close for r in rows]
    highs, lows = [r.high for r in rows], [r.low for r in rows]
    start = max(0, len(rows) - CONTEXT_BARS)
    inds = {
        "sma20": sma(closes, 20),
        "sma50": sma(closes, 50),
        "sma200": sma(closes, 200),
        "ema21": ema(closes, 21),
    }
    r14 = rsi(closes, 14)
    divs = [d for d in divergences(lows, highs, r14) if d.index >= start][-5:]
    levels = (
        await conn.execute(
            text("SELECT price, label FROM chart_level WHERE instrument_id = :iid ORDER BY price"),
            {"iid": iid},
        )
    ).all()
    tech = await svc.technicals(conn, iid, tf)
    piv = await svc.pivots(conn, iid, tf)
    stats = await svc.stats(conn, iid)
    season = await svc.seasonal(conn, iid, None, None)
    month = str(datetime.now(UTC).month)
    nxt = str(datetime.now(UTC).month % 12 + 1)
    ctx: dict[str, Any] = {
        "instrument": dict(inst),
        "timeframe": {"1d": "daily", "1w": "weekly"}[tf],
        "as_of": rows[-1].ts.date().isoformat(),
        "bars": {
            "columns": ["date", "open", "high", "low", "close", "volume"],
            "rows": [
                [r.ts.date().isoformat(), _r(r.open), _r(r.high), _r(r.low), _r(r.close), _r(r.volume, 0)]
                for r in rows[start:]
            ],
        },
        "indicators_last": {k: _r(v[-1]) for k, v in inds.items()} | {"rsi14": _r(r14[-1], 2)},
        "indicators_series_last_30": {k: [_r(x) for x in v[-30:]] for k, v in inds.items()}
        | {"rsi14": [_r(x, 2) for x in r14[-30:]]},
        "rsi_divergences": [
            {
                "date": rows[d.index].ts.date().isoformat(),
                "kind": d.kind,
                "rsi": _r(r14[d.index], 2),
                "prev_date": rows[d.prev_index].ts.date().isoformat(),
                "prev_rsi": _r(r14[d.prev_index], 2),
            }
            for d in divs
        ],
        "user_levels": [{"price": _r(lv.price), "label": lv.label} for lv in levels],
        "technical_rating": {k: tech[k] for k in ("summary", "as_of") if k in tech} if tech else None,
        "pivots": {
            "basis": piv["basis"],
            "classic": piv["levels"].get("classic"),
            "fibonacci": piv["levels"].get("fibonacci"),
        }
        if piv
        else None,
        "stats": {k: stats.get(k) for k in ("range_52w", "all_time_high", "performance", "avg_volume_30d")}
        if stats
        else None,
        "seasonality": {m: season.get("monthly_stats", {}).get(m) for m in (month, nxt)},
    }
    if inst["type"] == "stock":
        from app.market.stockdata import fair_value_summary  # local import: avoids import cycle

        fv = await fair_value_summary(conn.engine, iid)
        if fv.get("available"):
            ctx["fair_value"] = {k: fv[k] for k in ("fv_std", "upside", "period")}
    plain: dict[str, Any] = json.loads(json.dumps(ctx, default=str))  # plain JSON types only
    return plain


async def usage(engine: AsyncEngine, monthly_budget: float, daily_limit: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text("""
            SELECT
              COALESCE((SELECT sum(cost_usd) FROM ai_call_log
                        WHERE created_at >= date_trunc('month', now())), 0) AS spent_month,
              COALESCE((SELECT sum(reserved_usd) FROM chart_analysis
                        WHERE status IN ('queued','running')), 0)
                + COALESCE((SELECT sum(reserved_usd) FROM report
                            WHERE status IN ('queued','running')), 0) AS reserved,
              (SELECT count(*) FROM report WHERE created_at >= date_trunc('day', now())) AS reports_today,
              (SELECT count(*) FROM chart_analysis WHERE created_at >= date_trunc('day', now())) AS today,
              (SELECT count(*) FROM ai_call_log
                WHERE created_at >= date_trunc('month', now())) AS calls_month""")
                )
            )
            .mappings()
            .one()
        )
    spent, reserved = float(row["spent_month"]), float(row["reserved"])
    return {
        "spent_month_usd": round(spent, 4),
        "reserved_usd": round(reserved, 4),
        "budget_month_usd": monthly_budget,
        "remaining_usd": round(max(0.0, monthly_budget - spent - reserved), 4),
        "analyses_today": int(row["today"]),
        "reports_today": int(row["reports_today"]),
        "daily_limit": daily_limit,
        "calls_month": int(row["calls_month"]),
        "models": ai.MODELS,
        "default_model": ai.DEFAULT_MODEL,
        "estimate_usd": {m: round(ai.reservation_usd(m), 4) for m in ai.MODELS},
    }


async def create(
    engine: AsyncEngine, iid: int, tf: str, model: str, monthly_budget: float, daily_limit: int
) -> int:
    """Budget check + queued row in one transaction (advisory lock serialises concurrent requests)."""
    reserve = ai.reservation_usd(model)
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(7007)"))
        u = await usage(engine, monthly_budget, daily_limit)
        if u["analyses_today"] >= daily_limit:
            raise BudgetError(f"Tageslimit erreicht ({daily_limit} Analysen)")
        if u["remaining_usd"] < reserve:
            raise BudgetError(
                f"Monatsbudget erschöpft (verbraucht {u['spent_month_usd']:.2f} $ von {monthly_budget:.2f} $)"
            )
        ctx = await build_context(conn, iid, tf)
        aid = await conn.scalar(
            text("""
            INSERT INTO chart_analysis (instrument_id, tf, model, effort, status, reserved_usd, context)
            VALUES (:iid, :tf, :m, :e, 'queued', :r, CAST(:c AS jsonb)) RETURNING id"""),
            {"iid": iid, "tf": tf, "m": model, "e": ai.EFFORT, "r": reserve, "c": json.dumps(ctx)},
        )
    return int(aid)


async def fail(engine: AsyncEngine, aid: int, error: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE chart_analysis SET status = 'failed', error = :e, reserved_usd = 0, "
                "finished_at = now() WHERE id = :id AND status IN ('queued','running')"
            ),
            {"e": error[:300], "id": aid},
        )


async def run(engine: AsyncEngine, analyzer: ai.Analyzer, redis: Any, aid: int) -> str:
    """Worker side. Returns the final status."""
    async with engine.begin() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "UPDATE chart_analysis SET status = 'running' WHERE id = :id AND status = 'queued' "
                        "RETURNING model, context"
                    ),
                    {"id": aid},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return "skipped"
    png = await redis.get(PNG_KEY.format(aid))
    await redis.delete(PNG_KEY.format(aid))
    if not png:
        await fail(engine, aid, "Bild abgelaufen, bitte erneut starten")
        return "failed"
    if not analyzer.configured:
        await fail(
            engine, aid, "Anthropic API-Key nicht konfiguriert (./scripts/set-secret.sh anthropic_api_key)"
        )
        return "failed"
    res = await analyzer.analyze(bytes(png), dict(row["context"]), row["model"])
    cost = res.cost(row["model"])
    status = {"ok": "done", "refused": "refused", "error": "failed"}[res.status]
    async with engine.begin() as conn:
        if res.input_tokens or res.output_tokens or res.status != "error":
            await conn.execute(
                text("""
                INSERT INTO ai_call_log (feature, ref_id, model_requested, model_served, status, input_tokens,
                                         output_tokens, cache_read_tokens, cache_write_tokens, cost_usd,
                                         request_id, error)
                VALUES ('chart_analysis', :ref, :mr, :ms, :st, :it, :ot, :cr, :cw, :c, :rid, :err)"""),
                {
                    "ref": aid,
                    "mr": row["model"],
                    "ms": res.model_served,
                    "st": res.status,
                    "it": res.input_tokens,
                    "ot": res.output_tokens,
                    "cr": res.cache_read_tokens,
                    "cw": res.cache_write_tokens,
                    "c": cost,
                    "rid": res.request_id,
                    "err": res.error,
                },
            )
        await conn.execute(
            text("""
            UPDATE chart_analysis SET status = :s, result = CAST(:r AS jsonb), error = :e, reserved_usd = 0,
                   finished_at = now() WHERE id = :id"""),
            {"s": status, "r": json.dumps(res.result) if res.result else None, "e": res.error, "id": aid},
        )
    return status


def _out(r: Any, with_context: bool = False) -> dict[str, Any]:
    d = dict(r)
    for k in ("created_at", "finished_at"):
        d[k] = d[k].isoformat() if d.get(k) else None
    d["reserved_usd"] = float(d.get("reserved_usd") or 0)
    if d.get("cost_usd") is not None:
        d["cost_usd"] = float(d["cost_usd"])
    if not with_context:
        d.pop("context", None)
    return d


async def get(engine: AsyncEngine, aid: int) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        r = (
            (
                await conn.execute(
                    text("""
            SELECT a.id, a.instrument_id, i.symbol, a.tf, a.model, a.effort, a.status, a.reserved_usd,
                   a.context, a.result, a.error, a.created_at, a.finished_at,
                   (SELECT sum(cost_usd) FROM ai_call_log l
                     WHERE l.feature = 'chart_analysis' AND l.ref_id = a.id) AS cost_usd,
                   (SELECT max(model_served) FROM ai_call_log l
                     WHERE l.feature = 'chart_analysis' AND l.ref_id = a.id) AS model_served
            FROM chart_analysis a JOIN instrument i ON i.id = a.instrument_id WHERE a.id = :id"""),
                    {"id": aid},
                )
            )
            .mappings()
            .first()
        )
    return _out(r, with_context=True) if r else None


async def history(engine: AsyncEngine, iid: int, limit: int = 20) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
            SELECT a.id, a.tf, a.model, a.status, a.reserved_usd, a.error, a.created_at, a.finished_at,
                   a.result->>'summary' AS summary, a.result->>'confidence' AS confidence,
                   (SELECT sum(cost_usd) FROM ai_call_log l
                     WHERE l.feature = 'chart_analysis' AND l.ref_id = a.id) AS cost_usd
            FROM chart_analysis a WHERE a.instrument_id = :iid ORDER BY a.created_at DESC LIMIT :n"""),
            {"iid": iid, "n": limit},
        )
        return [_out(r) for r in rows.mappings()]


async def expire_stale(engine: AsyncEngine, minutes: int = 20) -> int:
    """Release reservations of analyses stuck in queued/running (worker restart etc.)."""
    async with engine.begin() as conn:
        res = await conn.execute(
            text("""
            UPDATE chart_analysis SET status = 'failed', error = 'Zeitüberschreitung', reserved_usd = 0,
                   finished_at = now()
            WHERE status IN ('queued','running') AND created_at < now() - make_interval(mins => :m)"""),
            {"m": minutes},
        )
    return int(res.rowcount or 0)
