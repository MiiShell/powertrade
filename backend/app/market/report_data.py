"""DB snapshot for a Claude stock report. Every number in a report (tables, charts, tool results) comes from
this one snapshot, which is stored with the report version so text, tables and charts stay consistent."""

import json
import math
from datetime import UTC, datetime
from statistics import median
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.market import details as svc
from app.market import stockdata
from app.market.fundamentals import load_series

YEARS = 10


def _r(v: Any, d: int = 4) -> Any:
    if isinstance(v, float):
        return None if not math.isfinite(v) else round(v, d)
    return v


def _pct(a: float | None, b: float | None) -> float | None:
    return round(a / b * 100, 2) if a is not None and b else None


def _growth(cur: float | None, prev: float | None) -> float | None:
    return round((cur / prev - 1) * 100, 2) if cur is not None and prev and prev > 0 else None


def _prev(prev: dict[str, Any] | None, key: str) -> float | None:
    return None if prev is None else prev.get(key)


def _cagr(first: float | None, last: float | None, years: int) -> float | None:
    if not first or not last or first <= 0 or last <= 0 or years <= 0:
        return None
    return round(float((last / first) ** (1 / years) - 1) * 100, 2)


def annual_table(series: dict[str, dict[int, float]], fy_close: dict[int, float]) -> list[dict[str, Any]]:
    """Per fiscal year: absolute values, per-share values, margins, growth, P/B and shareholder returns."""
    years = sorted({y for s in series.values() for y in s})[-(YEARS + 1) :]
    rows: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    for y in years:
        g = {
            k: series.get(k, {}).get(y)
            for k in (
                "revenue",
                "net_income",
                "operating_income",
                "eps_diluted",
                "shares_diluted",
                "operating_cf",
                "capex",
                "free_cf",
                "dps",
                "debt",
                "cash",
                "equity",
                "assets",
            )
        }
        fcf = g["free_cf"]
        if fcf is None and g["operating_cf"] is not None and g["capex"] is not None:
            fcf = g["operating_cf"] - abs(g["capex"])
        sh = g["shares_diluted"]
        bvps = g["equity"] / sh if g["equity"] is not None and sh else None
        close = fy_close.get(y)
        row = {
            "fiscal_year": y,
            **g,
            "free_cf": fcf,
            "operating_margin_pct": _pct(g["operating_income"], g["revenue"]),
            "net_margin_pct": _pct(g["net_income"], g["revenue"]),
            "fcf_margin_pct": _pct(fcf, g["revenue"]),
            "net_debt": (g["debt"] or 0) - (g["cash"] or 0)
            if g["debt"] is not None or g["cash"] is not None
            else None,
            "equity_ratio_pct": _pct(g["equity"], g["assets"]),
            "bvps": _r(bvps),
            "close_fy_end": close,
            "pb": _r(close / bvps, 2) if close and bvps and bvps > 0 else None,
            "dividends_paid_est": _r(g["dps"] * sh, 0) if g["dps"] is not None and sh else None,
            "payout_ratio_pct": _pct(g["dps"], g["eps_diluted"]) if (g["eps_diluted"] or 0) > 0 else None,
            "revenue_growth_pct": _growth(g["revenue"], _prev(prev, "revenue")),
            "eps_growth_pct": _growth(g["eps_diluted"], _prev(prev, "eps_diluted")),
            "dps_growth_pct": _growth(g["dps"], _prev(prev, "dps")),
            "shares_change_pct": _growth(sh, _prev(prev, "shares_diluted")),
        }
        rows.append({k: _r(v) for k, v in row.items()})
        prev = row
    return rows[-YEARS:]


async def _yearly_prices(engine: AsyncEngine, iid: int) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await svc.load_ohlcv(conn, iid, "1mo", 12 * 25)
    by_year: dict[int, list[Any]] = {}
    for r in rows:
        by_year.setdefault(r.ts.year, []).append(r)
    out = []
    prev_close = None
    for y in sorted(by_year)[-YEARS - 1 :]:
        bars = by_year[y]
        close = bars[-1].close
        out.append(
            {
                "year": y,
                "close": _r(close),
                "high": _r(max(b.high for b in bars)),
                "low": _r(min(b.low for b in bars)),
                "return_pct": _growth(close, prev_close),
                "partial_year": y == datetime.now(UTC).year,
            }
        )
        prev_close = close
    return out[-YEARS:]


def _max_drawdown(monthly: list[float]) -> float | None:
    peak, mdd = None, 0.0
    for c in monthly:
        peak = c if peak is None or c > peak else peak
        if peak:
            mdd = min(mdd, c / peak - 1)
    return round(mdd * 100, 2) if monthly else None


async def collect(engine: AsyncEngine, iid: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        inst = (
            (
                await conn.execute(
                    text(
                        "SELECT id, symbol, name, type, currency, isin, exchange, country FROM instrument "
                        "WHERE id = :iid"
                    ),
                    {"iid": iid},
                )
            )
            .mappings()
            .first()
        )
        if inst is None:
            raise LookupError("instrument not found")
        if inst["type"] != "stock":
            raise ValueError("reports are only available for stocks")
        profile = await svc.profile(conn, iid)
        stats = await svc.stats(conn, iid)
        tech = await svc.technicals(conn, iid, "1d")
        monthly = [r.close for r in await svc.load_ohlcv(conn, iid, "1mo", 120)]
    series = await load_series(engine, iid)
    if not series.get("eps_diluted"):
        raise ValueError("no fundamentals imported yet")
    fv = await stockdata.fair_value(engine, iid, series=series)
    card = await stockdata.scorecard(engine, iid)
    fy_close = {y["fiscal_year"]: y["close"] for y in fv["years"] if y.get("close")}
    annual = annual_table(series, fy_close)
    prices = await _yearly_prices(engine, iid)
    pbs = [a["pb"] for a in annual if a["pb"] and 0 < a["pb"] <= 100]
    first, last = annual[0], annual[-1]
    span = last["fiscal_year"] - first["fiscal_year"]
    m = card["metrics"]
    snap: dict[str, Any] = {
        "as_of": datetime.now(UTC).date().isoformat(),
        "instrument": dict(inst),
        "profile": {
            k: (profile or {}).get(k)
            for k in (
                "company_name",
                "sector",
                "industry",
                "country",
                "exchange",
                "ceo",
                "employees",
                "website",
                "ipo_date",
                "market_cap",
                "beta",
                "description",
                "source",
                "fetched_at",
            )
        }
        if profile
        else None,
        "market": {
            "price": stats.get("price"),
            "date": stats.get("date"),
            "range_52w": stats.get("range_52w"),
            "all_time_high": stats.get("all_time_high"),
            "performance_pct": stats.get("performance"),
            "max_drawdown_10y_pct": _max_drawdown(monthly),
        },
        "annual": annual,
        "growth": {
            "years": span,
            "revenue_cagr_pct": _cagr(first["revenue"], last["revenue"], span),
            "eps_cagr_pct": _cagr(first["eps_diluted"], last["eps_diluted"], span),
            "dps_cagr_pct": _cagr(first["dps"], last["dps"], span),
            "eps_trend_growth_10y_pct": m.get("earnings_growth_10y"),
            "eps_trend_growth_5y_pct": m.get("earnings_growth_5y"),
            "earnings_stability": m.get("earnings_stability"),
        },
        "prices_yearly": prices,
        "valuation": {
            "fv_std": fv["fv_std"],
            "upside_pct": fv["upside"],
            "buy_limit": fv["buy_limit"],
            "period_years": fv["period"],
            "median_multiples": fv["medians"],
            "used_multiples": fv["multiples"],
            "fair_values": fv["fair_value"],
            "expected_return_pct_pa": fv["expected_return"],
            "dividend_yield_pct": fv["dividend_yield"],
            "pb_current": _r(stats.get("price") / last["bvps"], 2)
            if stats.get("price") and last["bvps"]
            else None,
            "pb_median_10y": _r(median(pbs), 2) if pbs else None,
            "eps_basis": fv["eps_basis"],
            "corridor": fv["corridor"],
            "history_fv": fv["history"]["earnings_adj"],
        },
        "scores": {
            "profiles": {k: v["score"] for k, v in (card["profiles"] or {}).items()},
            "ranking_points": (card["ranking"] or {}).get("points"),
            "payback_years": m.get("payback_years"),
            "dividend_not_cut_years": m.get("dividend_not_cut_years"),
            "momentum_pct": m.get("momentum"),
        },
        "technicals": {"summary": tech.get("summary"), "as_of": tech.get("as_of")} if tech else None,
        "sources_db": {
            "fundamentals": card["run"],
            "prices": "Yahoo/Stooq (daily bars)",
            "profile": (profile or {}).get("source"),
        },
    }
    plain: dict[str, Any] = json.loads(json.dumps(snap, default=str))
    return plain


def numbers(obj: Any) -> list[float]:
    """All finite numbers in a snapshot (for the number check)."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        if math.isfinite(obj):
            out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(numbers(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(numbers(v))
    return out
