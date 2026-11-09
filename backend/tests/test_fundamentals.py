import json
from datetime import date

import pytest

from app.market.fundamentals import (
    Fact,
    fiscal_year_of,
    parse_fmp_dividends,
    parse_fmp_statement,
    parse_sec_companyfacts,
    split_adjust,
)
from app.market.providers import FixtureProvider, ProviderError, parse_yahoo_splits


def e(end: str, val: float, start: str | None = None, form: str = "10-K", filed: str = "2024-03-01", **kw):  # type: ignore[no-untyped-def]
    d = {"end": end, "val": val, "form": form, "filed": filed, "fp": "FY", **kw}
    if start:
        d["start"] = start
    return d


def facts_of(gaap: dict) -> dict[tuple[str, int], Fact]:  # type: ignore[type-arg]
    return {(f.metric, f.fiscal_year): f for f in parse_sec_companyfacts({"facts": {"us-gaap": gaap}})}


def test_fiscal_year_label() -> None:
    assert fiscal_year_of(date(2024, 1, 28)) == 2023  # NVDA FY ending January
    assert fiscal_year_of(date(2024, 9, 28)) == 2024  # AAPL FY ending September


def test_sec_annual_filtering_and_restatements() -> None:
    gaap = {
        "Revenues": {
            "units": {
                "USD": [
                    e("2023-12-31", 100.0, "2023-01-01"),
                    e("2023-12-31", 105.0, "2023-01-01", filed="2025-03-01"),  # restated later -> wins
                    e("2023-06-30", 50.0, "2023-04-01"),  # quarter -> ignored
                    e("2022-12-31", 80.0, "2022-01-01", form="10-Q"),  # wrong form -> ignored
                    e("2021-12-31", float("nan"), "2021-01-01"),  # not finite -> ignored
                ]
            }
        },
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {
                "USD": [
                    e("2022-12-31", 90.0, "2022-01-01"),  # preferred concept fills 2022
                ]
            }
        },
        "PaymentsToAcquirePropertyPlantAndEquipment": {
            "units": {"USD": [e("2023-12-31", -20.0, "2023-01-01")]}
        },
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {"USD": [e("2023-12-31", 70.0, "2023-01-01")]}
        },
        "LongTermDebt": {"units": {"USD": [e("2023-12-31", 300.0)]}},
    }
    f = facts_of(gaap)
    assert f[("revenue", 2023)].value == 105.0
    assert f[("revenue", 2022)].value == 90.0
    assert ("revenue", 2021) not in f
    assert f[("capex", 2023)].value == 20.0  # sign normalised
    assert f[("free_cf", 2023)].value == 50.0  # derived
    assert f[("debt", 2023)].value == 300.0


def test_split_adjust_uses_filing_date() -> None:
    splits = [(date(2024, 6, 10), 10.0)]
    old = Fact("eps_diluted", 2022, date(2023, 1, 29), 1.74, "USD/shares", "sec", date(2023, 2, 24))
    restated = Fact("eps_diluted", 2023, date(2024, 1, 28), 1.19, "USD/shares", "sec", date(2025, 2, 26))
    shares = Fact("shares_diluted", 2022, date(2023, 1, 29), 2.5e9, "shares", "sec", date(2023, 2, 24))
    rev = Fact("revenue", 2022, date(2023, 1, 29), 1e10, "USD", "sec", date(2023, 2, 24))
    out = {f.metric + str(f.fiscal_year): f.value for f in split_adjust([old, restated, shares, rev], splits)}
    assert out["eps_diluted2022"] == pytest.approx(0.174)
    assert out["eps_diluted2023"] == 1.19  # already on post-split basis
    assert out["shares_diluted2022"] == 2.5e10
    assert out["revenue2022"] == 1e10


def test_yahoo_splits() -> None:
    raw = json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "events": {
                            "splits": {
                                "1717939800": {
                                    "date": 1717939800,
                                    "numerator": 10,
                                    "denominator": 1,
                                    "splitRatio": "10:1",
                                },
                                "1": {"date": 1, "numerator": 1, "denominator": 1},
                            }
                        }
                    }
                ]
            }
        }
    ).encode()
    assert parse_yahoo_splits(raw) == [(date(2024, 6, 9), 10.0)]
    assert parse_yahoo_splits(b"{}") == []


def test_fmp_statements_and_dividends() -> None:
    inc = json.dumps(
        [
            {
                "date": "2024-09-28",
                "period": "FY",
                "reportedCurrency": "USD",
                "revenue": 391e9,
                "epsDiluted": 6.08,
                "netIncome": "x",
            }
        ]
    ).encode()
    f = {x.metric: x for x in parse_fmp_statement(inc, "income")}
    assert f["revenue"].value == 391e9 and f["eps_diluted"].fiscal_year == 2024 and "net_income" not in f
    cf = json.dumps([{"date": "2024-09-28", "period": "FY", "capitalExpenditure": -9.4e9}]).encode()
    assert parse_fmp_statement(cf, "cashflow")[0].value == 9.4e9
    with pytest.raises(ProviderError):
        parse_fmp_statement(json.dumps({"Error Message": "Premium"}).encode(), "income")
    div = json.dumps(
        [
            {"date": "2023-02-10", "adjDividend": 0.23},
            {"date": "2023-05-12", "adjDividend": 0.24},
            {"date": "2099-01-01", "adjDividend": 9},
        ]
    ).encode()
    d = parse_fmp_dividends(div)
    assert [(x.fiscal_year, x.value) for x in d] == [(2023, 0.47)]


async def test_fixture_companyfacts_roundtrip() -> None:
    data = await FixtureProvider().companyfacts(1045810)
    facts = parse_sec_companyfacts(data, "fixture")
    eps = sorted((f.fiscal_year, f.value) for f in facts if f.metric == "eps_diluted")
    assert len(eps) == 12 and eps[0] == (2014, 4.0)  # as reported (pre-split basis)
    splits = await FixtureProvider().splits("NVDA")
    adj = sorted((f.fiscal_year, f.value) for f in split_adjust(facts, splits) if f.metric == "eps_diluted")
    assert adj[0][1] == pytest.approx(1.0) and adj[-1][1] == pytest.approx(1.12**11)
    assert any(f.metric == "free_cf" for f in facts)
