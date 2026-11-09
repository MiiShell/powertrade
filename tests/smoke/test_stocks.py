"""Phase 4: fundamentals import (fixture EDGAR data), quality scores, ranking, stock list."""

import time

import httpx

from test_ingestion import _wait_for

KEYS = [
    "earnings_stability",
    "earnings_growth_5y",
    "dividend_yield",
    "dividend_growth_5y",
    "dividend_stability",
    "max_payback_years",
    "min_discount",
]


def _card(c: httpx.Client, iid: int) -> dict:
    r = c.get(f"/api/instruments/{iid}/scorecard")
    assert r.status_code == 200, r.text
    return r.json()


def test_stocks_require_auth(client: httpx.Client) -> None:
    assert client.get("/api/stocks").status_code == 401
    assert client.get("/api/instruments/1/scorecard").status_code == 401
    assert client.get("/api/ranking/strategy").status_code == 401


def test_fundamentals_imported_split_adjusted_and_scored(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    deadline = time.time() + 120
    while (card := _card(authed, iid))["profiles"] is None:
        assert time.time() < deadline, f"no scores: {card.get('run')}"
        time.sleep(3)
    eps = dict(card["fundamentals"]["eps_diluted"])
    assert abs(eps[2014] - 1.0) < 1e-6  # as-reported 4.0 adjusted for the 4:1 split
    assert abs(eps[2025] - 1.12**11) < 1e-6
    assert card["run"]["source"] == "fixture" and card["run"]["status"] == "success"
    m = card["metrics"]
    assert m["earnings_stability"] > 0.9 and 9 < m["earnings_growth_10y"] < 15
    assert m["payback_years"] is not None and m["dividend_not_cut_years"] == 11
    for k, p in card["profiles"].items():
        assert 1 <= p["score"] <= 10, k
    assert len(card["profiles"]["earnings_growth"]["criteria"]) == 5
    assert 0 <= card["ranking"]["points"] <= 100 and len(card["ranking"]["criteria"]) == 7


def test_crypto_has_no_scorecard(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "BTC")["id"]
    card = _card(authed, iid)
    assert card["profiles"] is None and card["ranking"] is None


def test_stock_list(authed: httpx.Client) -> None:
    stocks = authed.get("/api/stocks").json()["stocks"]
    nvda = next(s for s in stocks if s["symbol"] == "NVDA")
    assert all(1 <= v <= 10 for v in nvda["scores"].values())
    assert 0 <= nvda["ranking_points"] <= 100
    assert all(s["symbol"] not in ("BTC", "GOLD") for s in stocks)  # stocks only


def test_strategy_validation_and_update(authed: httpx.Client) -> None:
    s = authed.get("/api/ranking/strategy").json()
    assert set(s["targets"]) == set(KEYS)
    bad_keys = {"name": "x", "targets": {"earnings_stability": 1}, "weights": {}}
    assert authed.put("/api/ranking/strategy", json=bad_keys).status_code == 422
    bad_weight = {"name": "x", "targets": dict.fromkeys(KEYS, 1), "weights": {"dividend_yield": 99}}
    assert authed.put("/api/ranking/strategy", json=bad_weight).status_code == 422
    new = {"name": "Smoke", "targets": {**s["targets"], "dividend_yield": 1.0}, "weights": s["weights"]}
    r = authed.put("/api/ranking/strategy", json=new)
    assert (
        r.status_code == 200 and r.json()["name"] == "Smoke" and r.json()["targets"]["dividend_yield"] == 1.0
    )


def test_manual_refresh_limited_per_day(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    assert authed.post(f"/api/instruments/{iid}/fundamentals/refresh").status_code == 202
    again = authed.post(f"/api/instruments/{iid}/fundamentals/refresh")
    assert again.json()["status"] == "already requested today"
