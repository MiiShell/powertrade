from datetime import date, timedelta

import pytest

from app.market.analytics import OHLCV, DayBar, key_stats, pivot_points, seasonality


def test_pivots_match_tradingview_screenshot() -> None:
    # Derived from the TradingView BTCUSD pivots table (previous month OHLC, open > close)
    h, lo, c, o = 87249.05, 76141.02, 77424.0, 80000.0
    p = pivot_points(o, h, lo, c)
    assert p["classic"]["P"] == pytest.approx(80271.36, abs=0.05)
    assert p["classic"]["R3"] == pytest.approx(102487.41, abs=0.1)
    assert p["classic"]["S3"] == pytest.approx(58055.29, abs=0.1)
    assert p["fibonacci"]["R1"] == pytest.approx(84514.62, abs=0.1)
    assert p["camarilla"]["R1"] == pytest.approx(78442.22, abs=0.1)
    assert p["woodie"]["P"] == pytest.approx(79559.51, abs=0.1)
    assert p["woodie"]["R3"] == pytest.approx(94086.03, abs=0.2)
    assert p["woodie"]["S3"] == pytest.approx(60761.94, abs=0.2)
    assert p["dm"]["P"] == pytest.approx(79238.77, abs=0.1)
    assert p["dm"]["R1"] == pytest.approx(82336.52, abs=0.1)
    assert p["dm"]["R2"] is None


def _bars(start: date, days: int, f) -> list[DayBar]:  # type: ignore[no-untyped-def]
    return [DayBar(start + timedelta(days=i), f(i)) for i in range(days)]


def test_seasonality_paths_average_monthly() -> None:
    bars = _bars(date(2022, 1, 1), 365 * 3 + 1, lambda i: 100 + i * 0.1)
    s = seasonality(bars)
    years = {y["year"]: y for y in s["years"]}  # type: ignore[union-attr,index]
    assert set(years) == {2022, 2023, 2024}
    # 2023 base = last close of 2022
    first_2023 = years[2023]["points"][0]
    assert first_2023[0] == 0 and first_2023[1] > 0
    assert s["average_years"] == [2023, 2024]  # 2022 has no previous year
    assert s["monthly"]["2023"]["2"] > 0  # type: ignore[index]
    assert s["monthly_stats"]["3"]["positive_pct"] == 100.0  # type: ignore[index]
    narrow = seasonality(bars, 2023, 2023)
    assert [y["year"] for y in narrow["years"]] == [2023]  # type: ignore[union-attr]


def test_key_stats() -> None:
    start = date(2025, 1, 1)
    bars = [OHLCV(start + timedelta(days=i), 100 + i, 101 + i, 99 + i, 100 + i, 1000 + i) for i in range(400)]
    s = key_stats(bars)
    assert s["price"] == 499 and s["change"] == 1
    assert s["range_52w"] == [99 + 35, 101 + 399]
    assert s["avg_volume_30d"] == pytest.approx(sum(1000 + i for i in range(369, 399)) / 30)
    assert s["performance"]["1W"] == pytest.approx((499 / 492 - 1) * 100, abs=1e-3)  # type: ignore[index]
    assert s["range_week"][0] <= s["price"] <= s["range_week"][1]
    assert key_stats([]) == {}
