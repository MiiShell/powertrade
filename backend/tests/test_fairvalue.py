from datetime import date, timedelta

import pytest

from app.market import fairvalue as fv


def _closes(start: date, end: date, price: float) -> list[tuple[date, float]]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append((d, price))
        d += timedelta(days=1)
    return out


SERIES = {
    "eps_diluted": {2022: 2.0, 2023: 4.0},
    "shares_diluted": {2022: 100.0, 2023: 100.0},
    "operating_cf": {2022: 300.0, 2023: 500.0},  # 3.0, 5.0 per share
    "revenue": {2022: 1000.0, 2023: 2000.0},  # 10, 20 per share
    "dps": {2022: 1.0, 2023: 1.0},
}
ENDS = {2022: date(2022, 12, 31), 2023: date(2023, 12, 31)}


def test_per_share_and_daily_stepping() -> None:
    pts = fv.per_share_points(SERIES, ENDS)
    assert [p.ocf_ps for p in pts] == [3.0, 5.0] and [p.rev_ps for p in pts] == [10.0, 20.0]
    closes = [(date(2022, 6, 1), 50.0), (date(2023, 1, 2), 40.0), (date(2024, 1, 2), 80.0)]
    d = fv.daily_multiples(closes, pts)
    # before the first FY end nothing; then FY2022 (EPS 2) applies, from 2024 FY2023 (EPS 4)
    assert d["pe"] == [(date(2023, 1, 2), 20.0), (date(2024, 1, 2), 20.0)]
    assert d["dy"] == [(date(2023, 1, 2), 2.5), (date(2024, 1, 2), 1.25)]


def test_multiple_limits() -> None:
    assert fv.multiple_of(100.0, -1.0, "pe") is None  # loss year
    assert fv.multiple_of(500.0, 1.0, "pe") is None  # P/E 500 > 100
    assert fv.multiple_of(100.0, 1.0, "ps") is None  # P/S 100 > 30
    assert fv.multiple_of(20.0, 1.0, "pe") == 20.0


def test_full_model_lines_bands_corridor_return() -> None:
    today = date(2024, 12, 31)
    closes = _closes(date(2023, 1, 1), today, 60.0)
    out = fv.fair_value(SERIES, ENDS, closes, today)
    # FY2022 applies during 2023 (P/E 30), FY2023 during 2024 (P/E 15) -> median 15..30 (more 2024 days)
    assert 15.0 <= out["medians"]["pe"] <= 30.0
    pe = out["multiples"]["pe"]
    assert out["fv_std"] == pytest.approx(pe * 4.0) and out["fair_value"]["earnings_adj"] == out["fv_std"]
    assert out["eps_basis"] == "diluted"
    assert [b["k"] for b in out["bands"]] == list(range(-5, 6))
    assert out["bands"][5]["value"] == pytest.approx(out["fv_std"])
    assert out["buy_limit"] == pytest.approx(out["fv_std"] * 0.8)
    assert len(out["history"]["earnings_adj"]) == 2 and len(out["years"]) == 2
    assert out["years"][1]["d_eps"] == 100.0 and out["years"][1]["d_rev"] == 100.0
    assert out["dividend_yield"] == pytest.approx(1 / 60 * 100, abs=1e-3)
    assert out["corridor"] is None  # only 2 EPS years -> no trend
    assert out["expected_return"] is None


def test_overrides_and_period() -> None:
    today = date(2024, 12, 31)
    closes = _closes(date(2023, 1, 1), today, 60.0)
    out = fv.fair_value(SERIES, ENDS, closes, today, "5", {"pe": 25.0})
    assert out["multiples"]["pe"] == 25.0 and out["fv_std"] == 100.0 and out["upside"] == pytest.approx(66.67)
    with pytest.raises(ValueError, match="period"):
        fv.fair_value(SERIES, ENDS, closes, today, "7")
    with pytest.raises(ValueError, match="unknown"):
        fv.clean_overrides({"pb": 3})
    with pytest.raises(ValueError):
        fv.clean_overrides({"pe": 500})
    assert fv.clean_overrides({"pe": 20, "ps": None}) == {"pe": 20.0}


def test_corridor_is_capped_and_expected_return() -> None:
    eps = {2014 + i: 0.03 * 1.45**i for i in range(12)}  # ~45 % p.a. trend
    last = fv.FyPoint(2025, date(2026, 1, 25), eps[2025], None, None, None)
    cor = fv.corridor(eps, last, 40.0)
    assert cor is not None and cor["capped"] and cor["growth_used"] == 20.0 and cor["estimate"] == "trend"
    assert cor["points"][0]["eps"] == pytest.approx(eps[2025] * 1.2, rel=1e-4)
    assert len(cor["points"]) == 3
    price = cor["anchor"]["fair_value"]  # priced exactly at today's FV, 3y later FV x 1.2^3.x
    r = fv.expected_return(price, cor, date(2026, 1, 25), 1.0)
    assert r == pytest.approx(21.0, abs=0.1)
    assert fv.corridor(eps, None, 40.0) is None


def test_median_needs_enough_days_and_period_start() -> None:
    daily = {m: [(date(2024, 1, 1), 10.0)] * 10 for m in fv.MULTIPLES}
    assert fv.median_multiples(daily, None)["pe"] is None  # < MIN_DAYS
    assert fv.period_start(date(2024, 2, 29), "5") == date(2019, 2, 28)
    assert fv.period_start(date(2024, 5, 1), "all") is None
