import pytest

from app.market.indicators import divergences, ema, pivots, rsi, sma

# StockCharts "RSI" ChartSchool example (Wilder). StockCharts rounds the intermediate averages to
# 2 decimals (e.g. 70.53); exact arithmetic yields 70.46 -> tolerance 0.1.
CLOSES = [
    44.34,
    44.09,
    44.15,
    43.61,
    44.33,
    44.83,
    45.10,
    45.42,
    45.84,
    46.08,
    45.89,
    46.03,
    45.61,
    46.28,
    46.28,
    46.00,
    46.03,
    46.41,
    46.22,
    45.64,
]
RSI_EXPECTED = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97]


def test_sma() -> None:
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]
    assert sma([1, 2], 3) == [None, None]


def test_ema_seed_and_recursion() -> None:
    vals = [22.27, 22.19, 22.08, 22.17, 22.18, 22.13, 22.23, 22.43, 22.24, 22.29, 22.15, 22.39]
    out = ema(vals, 10)
    assert out[:9] == [None] * 9
    seed = sum(vals[:10]) / 10
    assert out[9] == pytest.approx(seed)
    a = 2 / 11
    assert out[10] == pytest.approx(a * vals[10] + (1 - a) * seed)
    assert out[11] == pytest.approx(22.24, abs=0.01)  # StockCharts EMA(10) example


def test_rsi_reference_values() -> None:
    out = rsi(CLOSES, 14)
    assert out[:14] == [None] * 14
    got = [round(v, 2) for v in out[14:] if v is not None]
    assert got == pytest.approx(RSI_EXPECTED, abs=0.1)
    assert got[0] == pytest.approx(70.46, abs=0.01)  # exact value


def test_rsi_edge_cases() -> None:
    assert rsi([1, 2, 3, 4, 5, 6], 3)[-1] == 100.0
    assert rsi([5, 5, 5, 5, 5], 3)[-1] == 50.0
    assert all(0 <= v <= 100 for v in rsi([float(x % 7) + 1 for x in range(200)], 14) if v is not None)


def test_pivots() -> None:
    v = [5.0, 4.0, 3.0, 4.0, 5.0, 6.0, 5.0, 4.0]
    assert pivots(v, 2, 2, "low") == [2]
    assert pivots(v, 2, 2, "high") == [5]
    assert pivots([1.0, 1.0, 1.0, 1.0, 1.0], 1, 1, "low") == []  # ties are not pivots


def test_bullish_divergence() -> None:
    # price: lower low at 20 vs 8; RSI: higher low at 20 vs 8
    n = 30
    lows = [100.0] * n
    lows[8], lows[20] = 90.0, 85.0
    osc: list[float | None] = [50.0] * n
    osc[8], osc[20] = 25.0, 35.0
    d = divergences(lows, [110.0] * n, osc, left=3, right=3)
    assert [(x.prev_index, x.index, x.kind) for x in d] == [(8, 20, "bull")]


def test_bearish_divergence_and_range_limit() -> None:
    n = 100
    highs = [100.0] * n
    highs[10], highs[25] = 110.0, 115.0
    osc: list[float | None] = [50.0] * n
    osc[10], osc[25] = 80.0, 70.0
    d = divergences([90.0] * n, highs, osc, left=3, right=3)
    assert [(x.prev_index, x.index, x.kind) for x in d] == [(10, 25, "bear")]
    assert divergences([90.0] * n, highs, osc, left=3, right=3, max_range=10) == []
