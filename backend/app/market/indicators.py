"""Technical indicators (pure Python, no NaN: warm-up values are None).

- SMA: arithmetic mean of the last n closes
- EMA: alpha = 2/(n+1), seeded with SMA(n) at index n-1 (TradingView convention)
- RSI: Wilder smoothing (alpha = 1/n), seeded with simple averages of the first n changes
- Divergences: regular bullish/bearish via RSI pivots (left/right lookback) compared with price
"""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Series = list[float | None]


def sma(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    if n < 1 or len(values) < n:
        return out
    window = sum(values[:n])
    out[n - 1] = window / n
    for i in range(n, len(values)):
        window += values[i] - values[i - n]
        out[i] = window / n
    return out


def ema(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    if n < 1 or len(values) < n:
        return out
    alpha = 2 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rsi(values: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(values)
    if n < 1 or len(values) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / n, losses / n
    out[n] = _rsi_value(avg_g, avg_l)
    for i in range(n + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0.0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0.0)) / n
        out[i] = _rsi_value(avg_g, avg_l)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def pivots(values: Series, left: int, right: int, kind: Literal["low", "high"]) -> list[int]:
    """Indices i where values[i] is the strict extreme within [i-left, i+right]."""
    idx: list[int] = []
    for i in range(left, len(values) - right):
        v = values[i]
        if v is None:
            continue
        window = values[i - left : i + right + 1]
        if any(w is None for w in window):
            continue
        others = [w for j, w in enumerate(window) if j != left]
        if (kind == "low" and all(v < w for w in others if w is not None)) or (
            kind == "high" and all(v > w for w in others if w is not None)
        ):
            idx.append(i)
    return idx


@dataclass(frozen=True)
class Divergence:
    index: int
    prev_index: int
    kind: Literal["bull", "bear"]


def divergences(
    lows: Sequence[float],
    highs: Sequence[float],
    osc: Series,
    left: int = 5,
    right: int = 5,
    min_range: int = 5,
    max_range: int = 60,
) -> list[Divergence]:
    """Regular divergences (TradingView 'RSI Divergence' logic):
    bull: price lower low  & RSI higher low  (at RSI pivot lows)
    bear: price higher high & RSI lower high (at RSI pivot highs)
    Signals are confirmed `right` bars after the pivot (no lookahead beyond that).
    """
    out: list[Divergence] = []
    for kind, piv_kind in (("bull", "low"), ("bear", "high")):
        pts = pivots(osc, left, right, piv_kind)  # type: ignore[arg-type]
        for a, b in itertools.pairwise(pts):
            if not min_range <= b - a <= max_range:
                continue
            oa, ob = osc[a], osc[b]
            assert oa is not None and ob is not None
            if kind == "bull" and ob > oa and lows[b] < lows[a]:
                out.append(Divergence(b, a, "bull"))
            if kind == "bear" and ob < oa and highs[b] > highs[a]:
                out.append(Divergence(b, a, "bear"))
    return sorted(out, key=lambda d: d.index)
