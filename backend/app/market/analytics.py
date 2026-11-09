"""Pivot points, seasonality and key statistics derived from stored bars."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


# ---------- pivots ----------
def pivot_points(o: float, h: float, lo: float, c: float) -> dict[str, dict[str, float | None]]:
    """TradingView formulas, based on the previous period's OHLC."""
    rng = h - lo
    p = (h + lo + c) / 3
    classic = {
        "R3": p + 2 * rng,
        "R2": p + rng,
        "R1": 2 * p - lo,
        "P": p,
        "S1": 2 * p - h,
        "S2": p - rng,
        "S3": p - 2 * rng,
    }
    fib = {
        "R3": p + rng,
        "R2": p + 0.618 * rng,
        "R1": p + 0.382 * rng,
        "P": p,
        "S1": p - 0.382 * rng,
        "S2": p - 0.618 * rng,
        "S3": p - rng,
    }
    cam = {
        "R3": c + rng * 1.1 / 4,
        "R2": c + rng * 1.1 / 6,
        "R1": c + rng * 1.1 / 12,
        "P": p,
        "S1": c - rng * 1.1 / 12,
        "S2": c - rng * 1.1 / 6,
        "S3": c - rng * 1.1 / 4,
    }
    wp = (h + lo + 2 * c) / 4
    woodie = {
        "R3": h + 2 * (wp - lo),
        "R2": wp + rng,
        "R1": 2 * wp - lo,
        "P": wp,
        "S1": 2 * wp - h,
        "S2": wp - rng,
        "S3": lo - 2 * (h - wp),
    }
    x = h + 2 * lo + c if c < o else 2 * h + lo + c if c > o else h + lo + 2 * c
    dm: dict[str, float | None] = {
        "R3": None,
        "R2": None,
        "R1": x / 2 - lo,
        "P": x / 4,
        "S1": x / 2 - h,
        "S2": None,
        "S3": None,
    }
    out: dict[str, dict[str, float | None]] = {
        "classic": dict(classic),
        "fibonacci": dict(fib),
        "camarilla": dict(cam),
        "woodie": dict(woodie),
        "dm": dm,
    }
    return {
        k: {lvl: (round(v, 6) if v is not None else None) for lvl, v in m.items()} for k, m in out.items()
    }


# ---------- seasonality ----------
@dataclass(frozen=True)
class DayBar:
    d: date
    close: float


def seasonality(
    bars: list[DayBar], from_year: int | None = None, to_year: int | None = None
) -> dict[str, object]:
    """YTD % path per year (vs. previous year's last close), average of complete years, monthly returns."""
    if not bars:
        return {"years": [], "average": [], "monthly": {}, "range": None}
    by_year: dict[int, list[DayBar]] = defaultdict(list)
    for b in bars:
        by_year[b.d.year].append(b)
    years_all = sorted(by_year)
    lo_y = max(from_year or years_all[0], years_all[0])
    hi_y = min(to_year or years_all[-1], years_all[-1])
    current = datetime.now(UTC).year

    paths: dict[int, list[tuple[int, float]]] = {}
    for y in range(lo_y, hi_y + 1):
        rows = by_year.get(y)
        if not rows:
            continue
        prev = by_year.get(y - 1)
        base = prev[-1].close if prev else rows[0].close
        paths[y] = [((b.d - date(y, 1, 1)).days, round((b.close / base - 1) * 100, 4)) for b in rows]

    # average over complete years (forward-filled per day of year)
    complete = [y for y in paths if y != current and by_year.get(y - 1)]
    avg: list[tuple[int, float]] = []
    if complete:
        filled: dict[int, list[float | None]] = {}
        for y in complete:
            arr: list[float | None] = [None] * 366
            last_v: float | None = 0.0
            pts = dict(paths[y])
            for day in range(366):
                if day in pts:
                    last_v = pts[day]
                arr[day] = last_v
            filled[y] = arr
        for day in range(366):
            vals = [filled[y][day] for y in complete if filled[y][day] is not None]
            if vals:
                avg.append((day, round(sum(v for v in vals if v is not None) / len(vals), 4)))

    # monthly returns: month-end close vs previous month-end close
    month_end: dict[tuple[int, int], float] = {}
    for b in bars:
        month_end[(b.d.year, b.d.month)] = b.close
    monthly: dict[int, dict[int, float]] = defaultdict(dict)
    for (y, m), close in month_end.items():
        py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
        if (py, pm) in month_end and lo_y <= y <= hi_y:
            monthly[y][m] = round((close / month_end[(py, pm)] - 1) * 100, 4)
    stats: dict[int, dict[str, float]] = {}
    for m in range(1, 13):
        rets = [monthly[y][m] for y in monthly if m in monthly[y] and y != current]
        if rets:
            stats[m] = {
                "avg": round(sum(rets) / len(rets), 4),
                "positive_pct": round(100 * sum(1 for v in rets if v > 0) / len(rets), 1),
                "n": len(rets),
            }

    return {
        "range": {"min_year": years_all[0], "max_year": years_all[-1], "from": lo_y, "to": hi_y},
        "years": [
            {"year": y, "points": [[d, v] for d, v in pts], "last": pts[-1][1] if pts else None}
            for y, pts in sorted(paths.items())
        ],
        "average": [[d, v] for d, v in avg],
        "average_years": complete,
        "monthly": {str(y): {str(m): v for m, v in ms.items()} for y, ms in sorted(monthly.items())},
        "monthly_stats": {str(m): s for m, s in stats.items()},
    }


# ---------- key statistics ----------
@dataclass(frozen=True)
class OHLCV:
    d: date
    o: float
    h: float
    lo: float
    c: float
    v: float | None


def key_stats(bars: list[OHLCV]) -> dict[str, object]:
    if not bars:
        return {}
    last = bars[-1]
    prev = bars[-2] if len(bars) > 1 else None
    year_ago = last.d - timedelta(days=365)
    last_year = [b for b in bars if b.d > year_ago]
    vols = [b.v for b in bars[-31:-1] if b.v is not None]

    def perf(days: int | None = None, since: date | None = None) -> float | None:
        cutoff = since or (last.d - timedelta(days=days or 0))
        ref = next((b for b in reversed(bars) if b.d <= cutoff), None)
        return round((last.c / ref.c - 1) * 100, 4) if ref else None

    ath = max(bars, key=lambda b: b.h)
    week_start = last.d - timedelta(days=last.d.weekday())
    week = [b for b in bars if b.d >= week_start]
    return {
        "date": last.d.isoformat(),
        "price": last.c,
        "change": round(last.c - prev.c, 6) if prev else None,
        "change_pct": round((last.c / prev.c - 1) * 100, 4) if prev else None,
        "volume": last.v,
        "avg_volume_30d": round(sum(vols) / len(vols), 2) if vols else None,
        "day_range": [last.lo, last.h],
        "range_week": [min(b.lo for b in week), max(b.h for b in week)],
        "range_52w": [min(b.lo for b in last_year), max(b.h for b in last_year)],
        "all_time_high": {"price": ath.h, "date": ath.d.isoformat()},
        "performance": {
            "1W": perf(7),
            "1M": perf(30),
            "3M": perf(91),
            "6M": perf(182),
            "YTD": perf(since=date(last.d.year - 1, 12, 31)),
            "1Y": perf(365),
            "5Y": perf(1826),
        },
    }
