"""Quality scores (3 Aktienfinder-style profiles, 1-10) and ranking (0-100). Spec: docs/SCORING.md v0.2."""

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any

# criterion -> (min, max) per profile; None = criterion not used in that profile
PROFILES: dict[str, dict[str, tuple[float, float] | None]] = {
    "dividend_yield": {  # Dividendenertrag
        "earnings_stability": (0, 1),
        "earnings_growth_10y": (0, 5),
        "payback_years": None,
        "momentum": (-15, 15),
        "discount": (1, 10),
        "dividend_yield": (0, 5),
        "dividend_stability": (0, 1),
        "dividend_growth_10y": (0, 5),
    },
    "dividend_growth": {  # Dividendenwachstum
        "earnings_stability": (0, 1),
        "earnings_growth_10y": (0, 15),
        "payback_years": None,
        "momentum": (-15, 15),
        "discount": (1, 10),
        "dividend_yield": (0, 2),
        "dividend_stability": (0, 1),
        "dividend_growth_10y": (0, 15),
    },
    "earnings_growth": {  # Gewinnwachstum
        "earnings_stability": (0, 1),
        "earnings_growth_10y": (0, 20),
        "payback_years": None,
        "momentum": (-15, 15),
        "discount": (1, 10),
        "dividend_yield": None,
        "dividend_stability": None,
        "dividend_growth_10y": None,
    },
}
DIVIDEND_CRITERIA = {"dividend_yield", "dividend_stability", "dividend_growth_10y"}


def _last(series: dict[int, float], n: int) -> list[tuple[int, float]]:
    return sorted(series.items())[-n:]


def stability(series: dict[int, float], n: int = 20) -> float | None:
    """Signed R^2 of OLS value ~ year (-1..1); None with < 3 points."""
    pts = _last(series, n)
    if len(pts) < 3:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx == 0 or syy == 0:
        return 0.0 if syy == 0 and my == 0 else 1.0 if syy == 0 else 0.0
    r2 = sxy * sxy / (sxx * syy)
    return round(math.copysign(r2, sxy), 4)


def trend_growth(series: dict[int, float], n: int) -> float | None:
    """CAGR (%) between fitted trendline start and end over the last n years; None if fit start <= 0."""
    pts = _last(series, n + 1)
    if len(pts) < 3:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx if sxx else 0.0
    start, end = my + slope * (xs[0] - mx), my + slope * (xs[-1] - mx)
    years = xs[-1] - xs[0]
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return round(float((end / start) ** (1 / years) - 1) * 100, 4)


def cagr(series: dict[int, float], n: int) -> float | None:
    pts = _last(series, n + 1)
    if len(pts) < 2 or pts[0][1] <= 0 or pts[-1][1] <= 0:
        return None
    years = pts[-1][0] - pts[0][0]
    return round(((pts[-1][1] / pts[0][1]) ** (1 / years) - 1) * 100, 4) if years > 0 else None


def years_not_cut(dps: dict[int, float]) -> int:
    pts = sorted(dps.items())
    n = 0
    for (_, prev), (_, cur) in zip(reversed(pts[:-1]), reversed(pts[1:]), strict=True):
        if cur + 1e-9 < prev or cur <= 0:
            break
        n += 1
    return n


def payback_years(debt: float | None, cash: float | None, fcf: dict[int, float]) -> float | None:
    """Net debt / mean FCF (3y). Net cash -> 0; FCF <= 0 -> inf; missing debt data -> None."""
    if debt is None:
        return None
    net = debt - (cash or 0.0)
    if net <= 0:
        return 0.0
    vals = [v for _, v in _last(fcf, 3)]
    if not vals:
        return None
    mean = sum(vals) / len(vals)
    return round(net / mean, 2) if mean > 0 else math.inf


def fair_value_std(eps: dict[int, float], fy_close: dict[int, float]) -> dict[str, float] | None:
    """Standard FV = median annual P/E (FY-end close / EPS, 0 < P/E <= 100, last 10 FY) x latest EPS."""
    pes = [
        fy_close[y] / e for y, e in _last(eps, 10) if y in fy_close and e > 0 and 0 < fy_close[y] / e <= 100
    ]
    latest = _last(eps, 1)
    if len(pes) < 3 or not latest or latest[0][1] <= 0:
        return None
    pe = median(pes)
    return {"fair_value": round(pe * latest[0][1], 4), "median_pe": round(pe, 2), "pe_years": len(pes)}


def discount(price: float, fv: float | None) -> float | None:
    if not fv or fv <= 0:
        return None
    return round(max(1.0, min(10.0, 5.5 - (price / fv - 1) / 0.10)), 2)


@dataclass
class Metrics:
    earnings_stability: float | None = None
    earnings_growth_10y: float | None = None
    earnings_growth_5y: float | None = None
    payback_years: float | None = None
    momentum: float | None = None
    discount: float | None = None
    dividend_yield: float | None = None
    dividend_stability: float | None = None
    dividend_growth_10y: float | None = None
    dividend_growth_5y: float | None = None
    dividend_cagr_5y: float | None = None
    dividend_not_cut_years: int | None = None
    payout_ratio: float | None = None
    fair_value: float | None = None
    median_pe: float | None = None
    eps_years: int = 0
    pays_dividend: bool = False
    is_financial: bool = False
    notes: list[str] = field(default_factory=list)


def compute_metrics(
    series: dict[str, dict[int, float]],
    price: float | None,
    sma200: float | None,
    fy_close: dict[int, float],
    is_financial: bool = False,
) -> Metrics:
    eps = series.get("eps_diluted", {})
    dps = {y: v for y, v in series.get("dps", {}).items() if v >= 0}
    m = Metrics(eps_years=len(eps), is_financial=is_financial)
    m.earnings_stability = stability(eps)
    m.earnings_growth_10y = trend_growth(eps, 10)
    m.earnings_growth_5y = trend_growth(eps, 5)
    if eps and m.earnings_growth_10y is None and len(eps) >= 3:
        m.notes.append("EPS-Trend nicht positiv -> Wachstum 0 Punkte")
    if len(eps) < 5:
        m.notes.append("weniger als 5 Geschäftsjahre -> geringe Aussagekraft")
    if not is_financial:
        debt = _last(series.get("debt", {}), 1)
        cash = _last(series.get("cash", {}), 1)
        m.payback_years = payback_years(
            debt[0][1] if debt else None, cash[0][1] if cash else None, series.get("free_cf", {})
        )
    if price and sma200:
        m.momentum = round((price / sma200 - 1) * 100, 4)
    fv = fair_value_std(eps, fy_close)
    if fv:
        m.fair_value, m.median_pe = fv["fair_value"], fv["median_pe"]
    if price:
        m.discount = discount(price, m.fair_value)
    last_dps = _last(dps, 1)
    m.pays_dividend = bool(last_dps and last_dps[0][1] > 0)
    if m.pays_dividend and price:
        m.dividend_yield = round(last_dps[0][1] / price * 100, 4)
        m.dividend_stability = stability(dps)
        m.dividend_growth_10y = trend_growth(dps, 10)
        m.dividend_growth_5y = trend_growth(dps, 5)
        m.dividend_cagr_5y = cagr(dps, 5)
        m.dividend_not_cut_years = years_not_cut(dps)
        last_eps = _last(eps, 1)
        if last_eps and last_eps[0][1] > 0 and last_eps[0][0] == last_dps[0][0]:
            m.payout_ratio = round(last_dps[0][1] / last_eps[0][1] * 100, 2)
    return m


def _sub(value: float | None, lo: float, hi: float) -> float | None:
    if value is None:
        return None
    return max(0.0, min(10.0, 10 * (value - lo) / (hi - lo)))


def subscore(criterion: str, value: float | None, scale: tuple[float, float]) -> float | None:
    if criterion == "payback_years":
        if value is None:
            return None
        return 10.0 if value <= 2 else 0.0 if math.isinf(value) else max(0.0, min(10.0, 20 / value))
    if criterion == "earnings_growth_10y" and value is None:
        return None
    return _sub(value, *scale)


def profile_scores(m: Metrics) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for profile, crits in PROFILES.items():
        if profile != "earnings_growth" and not m.pays_dividend:
            out[profile] = {"score": None, "criteria": [], "reason": "keine Dividende"}
            continue
        rows = []
        for crit, scale in crits.items():
            if crit == "payback_years":
                scale = (0, 0)  # special mapping (2 years -> 10, inf -> 0)
            if scale is None:
                continue
            value = getattr(m, crit)
            if crit == "earnings_growth_10y" and value is None and m.eps_years >= 3:
                s: float | None = 0.0  # non-positive trend is penalised, not ignored
            else:
                s = subscore(crit, value, scale)
            if crit == "payback_years" and m.is_financial:
                s = None
            rows.append(
                {
                    "criterion": crit,
                    "value": value if not (isinstance(value, float) and math.isinf(value)) else "inf",
                    "scale": None if crit == "payback_years" else list(scale),
                    "points": round(s, 2) if s is not None else None,
                    "warn": s is not None and s <= 2,
                }
            )
        valid = [float(r["points"]) for r in rows if isinstance(r["points"], int | float)]
        score = max(1, min(10, round(sum(valid) / len(valid)))) if valid else None
        out[profile] = {"score": score, "criteria": rows}
    return out


RANKING_CRITERIA = {
    "earnings_stability": ("earnings_stability", "higher"),
    "earnings_growth_5y": ("earnings_growth_5y", "higher"),
    "dividend_yield": ("dividend_yield", "higher"),
    "dividend_growth_5y": ("dividend_growth_5y", "higher"),
    "dividend_stability": ("dividend_stability", "higher"),
    "max_payback_years": ("payback_years", "lower"),
    "min_discount": ("discount", "higher"),
}


def ranking(m: Metrics, targets: dict[str, float], weights: dict[str, float]) -> dict[str, Any]:
    rows = []
    num = den = 0.0
    for key, (attr, direction) in RANKING_CRITERIA.items():
        soll = float(targets.get(key, 0) or 0)
        w = float(weights.get(key, 1) or 0)
        ist = getattr(m, attr)
        if direction == "higher":
            z = 0.0 if ist is None or ist <= 0 or soll <= 0 else min(1.0, ist / soll)
        elif ist is None:
            z = 0.0
        else:
            z = 1.0 if ist <= 0 else 0.0 if math.isinf(ist) else min(1.0, soll / ist) if soll > 0 else 0.0
        rows.append(
            {
                "criterion": key,
                "target": soll,
                "actual": "inf" if isinstance(ist, float) and math.isinf(ist) else ist,
                "achievement": round(z * 100, 1),
                "weight": w,
            }
        )
        num += w * z
        den += w
    return {"points": round(100 * num / den) if den else 0, "criteria": rows}
