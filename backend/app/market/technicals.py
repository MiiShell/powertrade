# mypy: disable-error-code="operator,type-var"
# (None-guarded numeric comparisons; guards are explicit via `ok`/`is not None` checks)
"""Technical ratings (TradingView-style): 11 oscillators + 15 moving averages -> Buy/Neutral/Sell.

Each indicator votes +1 (buy), 0 (neutral) or -1 (sell). Group rating = mean of votes;
summary = mean of the two group ratings. Labels: >0.5 strong buy, >0.1 buy, >=-0.1 neutral,
>=-0.5 sell, else strong sell. Rules follow TradingView's published technical-ratings logic
(simplified where noted).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.market.indicators import Series, ema, rsi, sma


# ---------- helpers ----------
def _valid(xs: Series) -> Series:
    return xs


def ema_opt(values: Series, n: int) -> Series:
    """EMA over a series that may start with None values."""
    out: Series = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None:
        return out
    tail = [v for v in values[start:]]
    if any(v is None for v in tail):
        return out
    res = ema([float(v) for v in tail if v is not None], n)
    out[start:] = res
    return out


def sma_opt(values: Series, n: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(n - 1, len(values)):
        w = values[i - n + 1 : i + 1]
        if all(v is not None for v in w):
            out[i] = sum(v for v in w if v is not None) / n
    return out


def rma(values: Series, n: int) -> Series:
    """Wilder's moving average (seeded with SMA)."""
    out: Series = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None or len(values) - start < n:
        return out
    seed = values[start : start + n]
    prev = sum(v for v in seed if v is not None) / n
    out[start + n - 1] = prev
    for i in range(start + n, len(values)):
        v = values[i]
        if v is None:
            return out
        prev = (prev * (n - 1) + v) / n
        out[i] = prev
    return out


def wma(values: Series, n: int) -> Series:
    out: Series = [None] * len(values)
    denom = n * (n + 1) / 2
    for i in range(n - 1, len(values)):
        w = values[i - n + 1 : i + 1]
        if all(v is not None for v in w):
            out[i] = sum((k + 1) * v for k, v in enumerate(w) if v is not None) / denom
    return out


def highest(values: Sequence[float], n: int) -> Series:
    return [max(values[i - n + 1 : i + 1]) if i >= n - 1 else None for i in range(len(values))]


def lowest(values: Sequence[float], n: int) -> Series:
    return [min(values[i - n + 1 : i + 1]) if i >= n - 1 else None for i in range(len(values))]


def _last(s: Series, k: int = 1) -> float | None:
    return s[-k] if len(s) >= k else None


# ---------- oscillators ----------
def stoch(
    h: Sequence[float], lo: Sequence[float], c: Sequence[float], k: int = 14, ks: int = 3, d: int = 3
) -> tuple[Series, Series]:
    hh, ll = highest(h, k), lowest(lo, k)
    raw: Series = [
        (
            100 * (c[i] - ll[i]) / (hh[i] - ll[i])
            if hh[i] is not None and ll[i] is not None and hh[i] != ll[i]
            else (50.0 if hh[i] is not None else None)
        )
        for i in range(len(c))
    ]
    kk = sma_opt(raw, ks)
    return kk, sma_opt(kk, d)


def cci(h: Sequence[float], lo: Sequence[float], c: Sequence[float], n: int = 20) -> Series:
    tp = [(h[i] + lo[i] + c[i]) / 3 for i in range(len(c))]
    m = sma(tp, n)
    out: Series = [None] * len(c)
    for i in range(n - 1, len(c)):
        mean = m[i]
        assert mean is not None
        dev = sum(abs(x - mean) for x in tp[i - n + 1 : i + 1]) / n
        out[i] = (tp[i] - mean) / (0.015 * dev) if dev else 0.0
    return out


def adx(
    h: Sequence[float], lo: Sequence[float], c: Sequence[float], n: int = 14
) -> tuple[Series, Series, Series]:
    plus_dm: Series = [None]
    minus_dm: Series = [None]
    tr: Series = [None]
    for i in range(1, len(c)):
        up, down = h[i] - h[i - 1], lo[i - 1] - lo[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])))
    atr, pdm, mdm = rma(tr, n), rma(plus_dm, n), rma(minus_dm, n)
    pdi: Series = [100 * p / a if p is not None and a else None for p, a in zip(pdm, atr, strict=True)]
    mdi: Series = [100 * m / a if m is not None and a else None for m, a in zip(mdm, atr, strict=True)]
    dx: Series = [
        100 * abs(p - m) / (p + m)
        if p is not None and m is not None and (p + m)
        else (0.0 if p is not None else None)
        for p, m in zip(pdi, mdi, strict=True)
    ]
    return rma(dx, n), pdi, mdi


def awesome(h: Sequence[float], lo: Sequence[float]) -> Series:
    mid = [(a + b) / 2 for a, b in zip(h, lo, strict=True)]
    f, s = sma(mid, 5), sma(mid, 34)
    return [a - b if a is not None and b is not None else None for a, b in zip(f, s, strict=True)]


def momentum(c: Sequence[float], n: int = 10) -> Series:
    return [c[i] - c[i - n] if i >= n else None for i in range(len(c))]


def macd(c: Sequence[float], fast: int = 12, slow: int = 26, sig: int = 9) -> tuple[Series, Series]:
    f, s = ema(c, fast), ema(c, slow)
    line: Series = [a - b if a is not None and b is not None else None for a, b in zip(f, s, strict=True)]
    return line, ema_opt(line, sig)


def stoch_rsi(
    c: Sequence[float], k: int = 3, d: int = 3, rsi_n: int = 14, st_n: int = 14
) -> tuple[Series, Series]:
    r = rsi(c, rsi_n)
    raw: Series = [None] * len(c)
    for i in range(len(c)):
        w = r[i - st_n + 1 : i + 1] if i >= st_n - 1 else []
        if len(w) == st_n and all(v is not None for v in w):
            vals = [v for v in w if v is not None]
            hi, lo_ = max(vals), min(vals)
            cur = r[i]
            assert cur is not None
            raw[i] = 100 * (cur - lo_) / (hi - lo_) if hi != lo_ else 50.0
    kk = sma_opt(raw, k)
    return kk, sma_opt(kk, d)


def williams_r(h: Sequence[float], lo: Sequence[float], c: Sequence[float], n: int = 14) -> Series:
    hh, ll = highest(h, n), lowest(lo, n)
    return [
        -100 * (hh[i] - c[i]) / (hh[i] - ll[i])
        if hh[i] is not None and ll[i] is not None and hh[i] != ll[i]
        else None
        for i in range(len(c))
    ]


def bull_bear_power(
    h: Sequence[float], lo: Sequence[float], c: Sequence[float], n: int = 13
) -> tuple[Series, Series]:
    e = ema(c, n)
    return [(h[i] - e[i]) + (lo[i] - e[i]) if e[i] is not None else None for i in range(len(c))], e


def ultimate(
    h: Sequence[float], lo: Sequence[float], c: Sequence[float], a: int = 7, b: int = 14, cc: int = 28
) -> Series:
    bp: list[float] = [0.0]
    tr: list[float] = [0.0]
    for i in range(1, len(c)):
        low_ = min(lo[i], c[i - 1])
        bp.append(c[i] - low_)
        tr.append(max(h[i], c[i - 1]) - low_)
    out: Series = [None] * len(c)
    for i in range(cc, len(c)):

        def avg(n: int, i: int = i) -> float:
            t = sum(tr[i - n + 1 : i + 1])
            return sum(bp[i - n + 1 : i + 1]) / t if t else 0.0

        out[i] = 100 * (4 * avg(a) + 2 * avg(b) + avg(cc)) / 7
    return out


# ---------- moving averages ----------
def vwma(c: Sequence[float], v: Sequence[float | None], n: int = 20) -> Series:
    out: Series = [None] * len(c)
    for i in range(n - 1, len(c)):
        vw = v[i - n + 1 : i + 1]
        if any(x is None for x in vw):
            continue
        vol = sum(x for x in vw if x is not None)
        if vol:
            out[i] = sum(c[i - n + 1 + k] * (vw[k] or 0.0) for k in range(n)) / vol
    return out


def hma(c: Sequence[float], n: int = 9) -> Series:
    half, full = wma(list(c), n // 2), wma(list(c), n)
    diff: Series = [
        2 * a - b if a is not None and b is not None else None for a, b in zip(half, full, strict=True)
    ]
    return wma(diff, int(math.sqrt(n)))


def ichimoku(
    h: Sequence[float], lo: Sequence[float], conv: int = 9, base: int = 26, span_b: int = 52, disp: int = 26
) -> dict[str, float | None]:
    def mid(n: int, end: int) -> float | None:
        if end - n + 1 < 0:
            return None
        return (max(h[end - n + 1 : end + 1]) + min(lo[end - n + 1 : end + 1])) / 2

    i = len(h) - 1
    j = i - disp + 1  # cloud plotted at i was computed at j
    conv_v, base_v = mid(conv, i), mid(base, i)
    a_c, b_c = mid(conv, j), mid(base, j)
    span_a = (a_c + b_c) / 2 if a_c is not None and b_c is not None else None
    return {"conversion": conv_v, "base": base_v, "span_a": span_a, "span_b": mid(span_b, j)}


# ---------- rating ----------
@dataclass
class Row:
    name: str
    value: float | None
    action: int  # +1 buy, 0 neutral, -1 sell


@dataclass
class Rating:
    oscillators: list[Row] = field(default_factory=list)
    moving_averages: list[Row] = field(default_factory=list)


def label(score: float | None) -> str:
    if score is None:
        return "neutral"
    if score > 0.5:
        return "strong_buy"
    if score > 0.1:
        return "buy"
    if score >= -0.1:
        return "neutral"
    if score >= -0.5:
        return "sell"
    return "strong_sell"


def _vote(buy: bool, sell: bool) -> int:
    return 1 if buy else -1 if sell else 0


def _pair(s: Series) -> tuple[float | None, float | None]:
    return _last(s), _last(s, 2)


def compute_rating(
    o: Sequence[float], h: Sequence[float], lo: Sequence[float], c: Sequence[float], v: Sequence[float | None]
) -> Rating:
    r = Rating()
    if len(c) < 2:
        return r
    close = c[-1]

    def osc(name: str, val: float | None, buy: bool, sell: bool) -> None:
        r.oscillators.append(Row(name, val, _vote(buy, sell) if val is not None else 0))

    x, xp = _pair(rsi(c, 14))
    osc(
        "Relative Strength Index (14)",
        x,
        x is not None and xp is not None and x < 30 and x > xp,
        x is not None and xp is not None and x > 70 and x < xp,
    )

    k, d = stoch(h, lo, c)
    kl, dl = _last(k), _last(d)
    osc(
        "Stochastic %K (14, 3, 3)",
        kl,
        kl is not None and dl is not None and kl < 20 and kl > dl,
        kl is not None and dl is not None and kl > 80 and kl < dl,
    )

    x, xp = _pair(cci(h, lo, c))
    osc(
        "Commodity Channel Index (20)",
        x,
        x is not None and xp is not None and x < -100 and x > xp,
        x is not None and xp is not None and x > 100 and x < xp,
    )

    a, pdi, mdi = adx(h, lo, c)
    al, p1, m1, p2, m2 = _last(a), _last(pdi), _last(mdi), _last(pdi, 2), _last(mdi, 2)
    ok = None not in (al, p1, m1, p2, m2)
    osc(
        "Average Directional Index (14)",
        al,
        ok and al > 20 and p2 < m2 and p1 > m1,
        ok and al > 20 and p2 > m2 and p1 < m1,
    )

    ao = awesome(h, lo)
    a1, a2, a3 = _last(ao), _last(ao, 2), _last(ao, 3)
    ok = None not in (a1, a2, a3)
    osc(
        "Awesome Oscillator",
        a1,
        ok and ((a2 < 0 < a1) or (a1 > 0 and a3 > a2 < a1)),
        ok and ((a2 > 0 > a1) or (a1 < 0 and a3 < a2 > a1)),
    )

    x, xp = _pair(momentum(c))
    osc(
        "Momentum (10)",
        x,
        x is not None and xp is not None and x > xp,
        x is not None and xp is not None and x < xp,
    )

    m, sig = macd(c)
    ml, sl = _last(m), _last(sig)
    osc(
        "MACD Level (12, 26)",
        ml,
        ml is not None and sl is not None and ml > sl,
        ml is not None and sl is not None and ml < sl,
    )

    k, d = stoch_rsi(c)
    kl, dl = _last(k), _last(d)
    osc(
        "Stochastic RSI Fast (3, 3, 14, 14)",
        kl,
        kl is not None and dl is not None and kl < 20 and kl > dl,
        kl is not None and dl is not None and kl > 80 and kl < dl,
    )

    x, xp = _pair(williams_r(h, lo, c))
    osc(
        "Williams Percent Range (14)",
        x,
        x is not None and xp is not None and x < -80 and x > xp,
        x is not None and xp is not None and x > -20 and x < xp,
    )

    bbp, e13 = bull_bear_power(h, lo, c)
    x, xp = _pair(bbp)
    e1, e2 = _pair(e13)
    ok = None not in (x, xp, e1, e2)
    osc(
        "Bull Bear Power",
        x,
        ok and e1 > e2 and x < 0 and x > xp,
        ok and e1 < e2 and x > 0 and x < xp,
    )

    x = _last(ultimate(h, lo, c))
    osc("Ultimate Oscillator (7, 14, 28)", x, x is not None and x > 70, x is not None and x < 30)

    def ma(name: str, val: float | None) -> None:
        r.moving_averages.append(Row(name, val, _vote(val < close, val > close) if val is not None else 0))

    for n in (10, 20, 30, 50, 100, 200):
        ma(f"Exponential Moving Average ({n})", _last(ema(c, n)))
        ma(f"Simple Moving Average ({n})", _last(sma(c, n)))
    ich = ichimoku(h, lo)
    base, conv, sa, sb = ich["base"], ich["conversion"], ich["span_a"], ich["span_b"]
    ok = None not in (base, conv, sa, sb)
    r.moving_averages.append(
        Row(
            "Ichimoku Base Line (9, 26, 52, 26)",
            base,
            _vote(
                # TradingView: also requires a bullish/bearish cloud (lead line 1 vs. lead line 2)
                ok and close > max(sa, sb) and sa > sb and conv > base and close > base,
                ok and close < min(sa, sb) and sa < sb and conv < base and close < base,
            ),
        )
    )
    ma("Volume Weighted Moving Average (20)", _last(vwma(c, v)))
    ma("Hull Moving Average (9)", _last(hma(c)))
    return r


def summarize(r: Rating) -> dict[str, object]:
    def group(rows: list[Row]) -> dict[str, object]:
        votes = [x.action for x in rows if x.value is not None]
        score = sum(votes) / len(votes) if votes else None
        return {
            "score": round(score, 4) if score is not None else None,
            "label": label(score),
            "counts": {"sell": votes.count(-1), "neutral": votes.count(0), "buy": votes.count(1)},
            "rows": [
                {
                    "name": x.name,
                    "value": round(x.value, 6) if x.value is not None else None,
                    "action": {1: "buy", 0: "neutral", -1: "sell"}[x.action],
                }
                for x in rows
            ],
        }

    osc, mas = group(r.oscillators), group(r.moving_averages)
    scores = [float(s) for s in (osc["score"], mas["score"]) if isinstance(s, int | float)]
    summary_score = sum(scores) / len(scores) if scores else None
    oc, mc = osc["counts"], mas["counts"]
    assert isinstance(oc, dict) and isinstance(mc, dict)
    return {
        "summary": {
            "score": round(summary_score, 4) if summary_score is not None else None,
            "label": label(summary_score),
            "counts": {k: oc[k] + mc[k] for k in ("sell", "neutral", "buy")},
        },
        "oscillators": osc,
        "moving_averages": mas,
    }
