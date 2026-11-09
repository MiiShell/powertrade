"""Fair value - standard model (Aktienfinder-style). Spec: docs/SCORING.md section 4 (+ section 8 notes).

Pure functions only (no DB). Fundamentals are annual: each fiscal year's per-share values apply from its
period end until the next fiscal year ends ("daily-stepped"). Adjusted EPS is not available from free
sources, so "bereinigt" uses diluted EPS (flagged in the result).
"""

import bisect
import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any

from app.market.scores import trend_growth

PERIODS = ("5", "8", "10", "15", "20", "all")
DEFAULT_PERIOD = "10"
MULTIPLES = ("pe", "pcf", "ps", "dy")  # KGV, KCV, KUV, Dividendenrendite (%)
# Valid ranges before taking the median (SCORING.md section 0); dividend yield in % (0, 30].
LIMITS: dict[str, tuple[float, float]] = {"pe": (0, 100), "pcf": (0, 100), "ps": (0, 30), "dy": (0, 30)}
OVERRIDE_LIMITS: dict[str, tuple[float, float]] = {
    "pe": (1, 100),
    "pcf": (1, 100),
    "ps": (0.1, 30),
    "dy": (0.01, 30),
}
LINES = {"earnings_adj": "pe", "cashflow": "pcf", "revenue": "ps", "dividend": "dy"}
STD_LINE = "earnings_adj"  # FV_std = FV bereinigt
MIN_DAYS = 60  # min. daily samples for a median multiple
BAND_STEPS = tuple(range(-5, 6))  # FV_std x (1 + k x 10 %)
CORRIDOR_YEARS = 3
CORRIDOR_GROWTH_CAP = 20.0  # % p.a., trend extrapolation is clamped to +-cap
MARGIN_OF_SAFETY = 0.20


@dataclass(frozen=True)
class FyPoint:
    fiscal_year: int
    period_end: date
    eps: float | None
    ocf_ps: float | None
    rev_ps: float | None
    dps: float | None


def per_share_points(series: dict[str, dict[int, float]], period_ends: dict[int, date]) -> list[FyPoint]:
    """Annual per-share values (split-adjusted inputs). OCF/revenue per share via diluted shares."""
    shares = series.get("shares_diluted", {})

    def ps(metric: str, y: int) -> float | None:
        v, sh = series.get(metric, {}).get(y), shares.get(y)
        return v / sh if v is not None and sh else None

    out = []
    for y in sorted(period_ends):
        p = FyPoint(
            y,
            period_ends[y],
            series.get("eps_diluted", {}).get(y),
            ps("operating_cf", y),
            ps("revenue", y),
            series.get("dps", {}).get(y),
        )
        if any(v is not None for v in (p.eps, p.ocf_ps, p.rev_ps, p.dps)):
            out.append(p)
    return out


def _value(p: FyPoint, multiple: str) -> float | None:
    return {"pe": p.eps, "pcf": p.ocf_ps, "ps": p.rev_ps, "dy": p.dps}[multiple]


def multiple_of(close: float, base: float | None, multiple: str) -> float | None:
    """Price multiple (or dividend yield in %) if base is positive and the result lies in its valid range."""
    if base is None or base <= 0 or close <= 0:
        return None
    v = base / close * 100 if multiple == "dy" else close / base
    lo, hi = LIMITS[multiple]
    return v if lo < v <= hi else None


def daily_multiples(
    closes: list[tuple[date, float]], points: list[FyPoint]
) -> dict[str, list[tuple[date, float]]]:
    """Per trading day: multiple vs. the latest fiscal year that ended on or before that day."""
    ends = [p.period_end for p in points]
    out: dict[str, list[tuple[date, float]]] = {m: [] for m in MULTIPLES}
    for d, close in closes:
        i = bisect.bisect_right(ends, d) - 1
        if i < 0:
            continue
        for m in MULTIPLES:
            v = multiple_of(close, _value(points[i], m), m)
            if v is not None:
                out[m].append((d, v))
    return out


def period_start(today: date, period: str) -> date | None:
    if period == "all":
        return None
    years = int(period)
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # Feb 29
        return today.replace(year=today.year - years, day=28)


def median_multiples(
    daily: dict[str, list[tuple[date, float]]], since: date | None
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for m, rows in daily.items():
        vals = [v for d, v in rows if since is None or d >= since]
        out[m] = round(median(vals), 4) if len(vals) >= MIN_DAYS else None
    return out


def fv_from(multiple: str, avg: float | None, base: float | None) -> float | None:
    if avg is None or base is None or base <= 0:
        return None
    return round(base / (avg / 100) if multiple == "dy" else avg * base, 4)


def corridor(eps_series: dict[int, float], last: FyPoint | None, pe: float | None) -> dict[str, Any] | None:
    """3-year corridor without consensus: EPS x (1 + TrendGrowth)^t x avg P/E (estimate=trend)."""
    if last is None or last.eps is None or last.eps <= 0 or pe is None:
        return None
    g = trend_growth(eps_series, 10)
    if g is None:
        return None
    g_used = max(-CORRIDOR_GROWTH_CAP, min(CORRIDOR_GROWTH_CAP, g))
    pts = []
    for t in range(1, CORRIDOR_YEARS + 1):
        eps_t = last.eps * (1 + g_used / 100) ** t
        pts.append(
            {
                "fiscal_year": last.fiscal_year + t,
                "date": _add_years(last.period_end, t).isoformat(),
                "eps": round(eps_t, 4),
                "fair_value": round(pe * eps_t, 4),
            }
        )
    return {
        "estimate": "trend",
        "growth": g,
        "growth_used": g_used,
        "capped": g_used != g,
        "anchor": {
            "date": last.period_end.isoformat(),
            "eps": last.eps,
            "fair_value": round(pe * last.eps, 4),
        },
        "points": pts,
    }


def _add_years(d: date, years: float) -> date:
    return d + timedelta(days=round(365.25 * years))


def fv_at(cor: dict[str, Any], when: date) -> float | None:
    """Corridor fair value at a date (exponential between anchor and points, extrapolated beyond)."""
    anchor = date.fromisoformat(cor["anchor"]["date"])
    t = (when - anchor).days / 365.25
    if t < 0:
        return None
    base, g = float(cor["anchor"]["fair_value"]), float(cor["growth_used"])
    return round(base * math.pow(1 + g / 100, t), 4)


def expected_return(
    price: float | None, cor: dict[str, Any] | None, today: date, div_yield: float | None
) -> float | None:
    """Rendite Fairer Wert (% p.a.): (FV(t+3) / price)^(1/3) - 1 + dividend yield."""
    if not price or price <= 0 or cor is None:
        return None
    target = fv_at(cor, _add_years(today, CORRIDOR_YEARS))
    if not target or target <= 0:
        return None
    growth = float((target / price) ** (1 / CORRIDOR_YEARS)) - 1
    return round(growth * 100 + (div_yield or 0.0), 4)


def _pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev <= 0:
        return None
    return round((cur / prev - 1) * 100, 2)


def yearly_table(points: list[FyPoint], fy_close: dict[int, float]) -> list[dict[str, Any]]:
    rows = []
    prev: FyPoint | None = None
    for p in points:
        c = fy_close.get(p.fiscal_year)
        mult = {
            m: (round(v, 2) if c and (v := multiple_of(c, _value(p, m), m)) is not None else None)
            for m in MULTIPLES
        }
        rows.append(
            {
                "fiscal_year": p.fiscal_year,
                "period_end": p.period_end.isoformat(),
                "close": c,
                "eps": p.eps,
                "ocf_ps": round(p.ocf_ps, 4) if p.ocf_ps is not None else None,
                "rev_ps": round(p.rev_ps, 4) if p.rev_ps is not None else None,
                "dps": p.dps,
                **mult,
                "d_eps": _pct(p.eps, prev.eps if prev else None),
                "d_ocf": _pct(p.ocf_ps, prev.ocf_ps if prev else None),
                "d_rev": _pct(p.rev_ps, prev.rev_ps if prev else None),
                "d_dps": _pct(p.dps, prev.dps if prev else None),
            }
        )
        prev = p
    return rows


def clean_overrides(raw: dict[str, Any]) -> dict[str, float]:
    """Keep only known multiples with finite values inside OVERRIDE_LIMITS (raises ValueError otherwise)."""
    out: dict[str, float] = {}
    for k, v in raw.items():
        if k not in OVERRIDE_LIMITS:
            raise ValueError(f"unknown multiple: {k}")
        if v is None:
            continue
        f = float(v)
        lo, hi = OVERRIDE_LIMITS[k]
        if not math.isfinite(f) or not lo <= f <= hi:
            raise ValueError(f"{k} must be {lo}..{hi}")
        out[k] = round(f, 4)
    return out


def weekly(closes: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Last close of each ISO week (chart payload)."""
    out: dict[tuple[int, int], tuple[date, float]] = {}
    for d, c in closes:
        out[d.isocalendar()[:2]] = (d, c)
    return list(out.values())


def fair_value(
    series: dict[str, dict[int, float]],
    period_ends: dict[int, date],
    closes: list[tuple[date, float]],
    today: date,
    period: str = DEFAULT_PERIOD,
    overrides: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Full standard fair value model for one stock."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {PERIODS}")
    overrides = overrides or {}
    points = per_share_points(series, period_ends)
    daily = daily_multiples(closes, points)
    medians = median_multiples(daily, period_start(today, period))
    avg = {m: overrides.get(m, medians[m]) for m in MULTIPLES}
    price = closes[-1][1] if closes else None
    last = points[-1] if points else None
    last_eps = next((p for p in reversed(points) if p.eps is not None), None)

    current = {line: fv_from(m, avg[m], _latest(points, m)) for line, m in LINES.items()}
    fv_std = current[STD_LINE]
    history = {
        line: [
            {"date": p.period_end.isoformat(), "fiscal_year": p.fiscal_year, "value": v}
            for p in points
            if (v := fv_from(m, avg[m], _value(p, m))) is not None
        ]
        for line, m in LINES.items()
    }
    cor = corridor(series.get("eps_diluted", {}), last_eps, avg["pe"])
    div_yield = round(last.dps / price * 100, 4) if last and last.dps and price else None
    fy_close = _fy_close(closes, points)
    return {
        "as_of": today.isoformat(),
        "period": period,
        "periods": list(PERIODS),
        "price": price,
        "eps_basis": "diluted",  # no adjusted-EPS source: "bereinigt" == diluted EPS
        "medians": medians,
        "overrides": overrides,
        "multiples": avg,
        "fair_value": current,
        "fv_std": fv_std,
        "upside": round((fv_std / price - 1) * 100, 2) if fv_std and price else None,
        "buy_limit": round(fv_std * (1 - MARGIN_OF_SAFETY), 4) if fv_std else None,
        "margin_of_safety": MARGIN_OF_SAFETY,
        "bands": [{"k": k, "pct": k * 10, "value": round(fv_std * (1 + k / 10), 4)} for k in BAND_STEPS]
        if fv_std
        else [],
        "history": history,
        "corridor": cor,
        "expected_return": expected_return(price, cor, today, div_yield),
        "dividend_yield": div_yield,
        "dps": last.dps if last else None,
        "years": yearly_table(points, fy_close),
        "prices": [[d.isoformat(), c] for d, c in weekly(closes)],
    }


def _latest(points: list[FyPoint], multiple: str) -> float | None:
    """Base value of the most recent fiscal year that has it (e.g. EPS missing in the newest FMP row)."""
    return next((v for p in reversed(points) if (v := _value(p, multiple)) is not None), None)


def _fy_close(closes: list[tuple[date, float]], points: list[FyPoint]) -> dict[int, float]:
    """Last close on or before each fiscal year end."""
    days = [d for d, _ in closes]
    out = {}
    for p in points:
        i = bisect.bisect_right(days, p.period_end) - 1
        if i >= 0 and (p.period_end - days[i]).days <= 10:
            out[p.fiscal_year] = closes[i][1]
    return out
