import math

import pytest

from app.market.scores import (
    Metrics,
    cagr,
    compute_metrics,
    discount,
    payback_years,
    profile_scores,
    ranking,
    stability,
    trend_growth,
    years_not_cut,
)

GROW = {2014 + i: 1.0 * 1.10**i for i in range(11)}


def test_stability_and_growth() -> None:
    assert stability(GROW) == pytest.approx(0.98, abs=0.02)
    assert stability({y: 10 - i for i, y in enumerate(range(2015, 2025))}) == pytest.approx(-1.0)
    assert stability({2020: 1.0, 2021: 1.0}) is None
    assert trend_growth(GROW, 10) == pytest.approx(10.0, abs=1.5)
    assert trend_growth({y: 5 - i for i, y in enumerate(range(2015, 2025))}, 10) is None  # fitted end <= 0
    assert trend_growth(GROW, 10) == pytest.approx(10.0, abs=1e-9)  # log-linear: exact for exponential series


def test_trend_growth_exponential_and_mixed_sign() -> None:
    # NVDA-like: x40 in 10 years; a linear fit starts <= 0, the log-linear fit gives ~44.6 % p.a.
    expo = {2015 + i: 0.03 * 1.446**i for i in range(11)}
    assert trend_growth(expo, 10) == pytest.approx(44.6, abs=0.1)
    # a non-positive value -> linear fallback (here a rising trend with a loss year)
    mixed = {2015: 1.0, 2016: 2.0, 2017: -0.5, 2018: 4.0, 2019: 5.0, 2020: 6.0}
    g = trend_growth(mixed, 10)
    assert g is not None and g > 0
    assert trend_growth({2020: 1.0, 2021: 2.0}, 10) is None  # < 3 points
    assert cagr(GROW, 5) == pytest.approx(10.0, abs=1e-6)


def test_dividend_helpers() -> None:
    assert years_not_cut({2018: 1, 2019: 1.1, 2020: 1.0, 2021: 1.1, 2022: 1.2}) == 2
    assert years_not_cut({2020: 1}) == 0
    assert payback_years(100, 150, {2023: 10}) == 0.0
    assert payback_years(100, 0, {2021: 10, 2022: 20, 2023: 30}) == 5.0
    assert math.isinf(payback_years(100, 0, {2023: -5}) or 0)
    assert payback_years(None, 0, {2023: 1}) is None


def test_discount() -> None:
    assert discount(80.0, 80.0) == 5.5
    assert discount(40.0, 80.0) == 10.0  # 50 % below FV -> capped
    assert discount(200.0, 80.0) == 1.0
    assert discount(80.0, None) is None


def _series(dps: bool = True) -> dict[str, dict[int, float]]:
    s = {
        "eps_diluted": dict(GROW),
        "free_cf": {2022: 5e8, 2023: 6e8, 2024: 7e8},
        "debt": {2024: 2e9},
        "cash": {2024: 8e8},
    }
    if dps:
        s["dps"] = {2014 + i: 0.3 * 1.08**i for i in range(11)}
    return s


def test_profiles_and_ranking() -> None:
    m = compute_metrics(_series(), price=30.0, sma200=28.0, fv_std=40.0, median_pe=15.0)
    assert m.fair_value == 40.0 and m.discount == 8.0  # 25 % below FV_std
    assert m.pays_dividend and m.payback_years == 2.0 and m.momentum == pytest.approx(7.1429, abs=1e-3)
    p = profile_scores(m)
    assert set(p) == {"dividend_yield", "dividend_growth", "earnings_growth"}
    assert all(1 <= p[k]["score"] <= 10 for k in p)
    assert len(p["earnings_growth"]["criteria"]) == 5 and len(p["dividend_yield"]["criteria"]) == 8
    r = ranking(
        m,
        {
            "earnings_stability": 0.9,
            "earnings_growth_5y": 10,
            "dividend_yield": 2,
            "dividend_growth_5y": 8,
            "dividend_stability": 0.9,
            "max_payback_years": 4,
            "min_discount": 6,
        },
        {},
    )
    assert 0 <= r["points"] <= 100 and len(r["criteria"]) == 7
    payback = next(c for c in r["criteria"] if c["criterion"] == "max_payback_years")
    assert payback["achievement"] == 100.0  # 2 years <= target 4


def test_no_dividend_profiles_na_and_negative_trend_penalised() -> None:
    m = compute_metrics(_series(dps=False), price=30.0, sma200=None)
    p = profile_scores(m)
    assert p["dividend_yield"]["score"] is None and p["earnings_growth"]["score"] is not None
    bad = compute_metrics({"eps_diluted": {y: 5 - i for i, y in enumerate(range(2015, 2025))}}, 10.0, 10.0)
    g = next(
        c
        for c in profile_scores(bad)["earnings_growth"]["criteria"]
        if c["criterion"] == "earnings_growth_10y"
    )
    assert g["points"] == 0.0


def test_financials_skip_payback() -> None:
    m = Metrics(earnings_stability=0.9, is_financial=True, payback_years=None, eps_years=10)
    rows = profile_scores(m)["earnings_growth"]["criteria"]
    assert next(r for r in rows if r["criterion"] == "payback_years")["points"] is None
