"""Phase 4/5: fundamentals import (fixture EDGAR data), quality scores, ranking, stock list, fair value."""

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


def test_fair_value_model_and_settings(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    assert authed.get(f"/api/instruments/{iid}/fairvalue").status_code == 200
    fv = authed.get(f"/api/instruments/{iid}/fairvalue", params={"period": "5"}).json()
    assert fv["available"] and fv["period"] == "5" and fv["eps_basis"] == "diluted"
    assert fv["fv_std"] and fv["fv_std"] > 0 and len(fv["bands"]) == 11 and fv["prices"]
    assert fv["years"] and set(fv["fair_value"]) == {"earnings_adj", "cashflow", "revenue", "dividend"}
    assert fv["corridor"]["estimate"] == "trend" and len(fv["corridor"]["points"]) == 3
    # scorecard discount is based on FV_std of the engine
    card = _card(authed, iid)
    assert card["fair_value"]["fv_std"] == card["metrics"]["fair_value"]
    # settings: validation, override, reset
    url = f"/api/instruments/{iid}/fairvalue/settings"
    assert authed.get(f"/api/instruments/{iid}/fairvalue", params={"period": "7"}).status_code == 422
    assert authed.put(url, json={"period": "10", "overrides": {"pb": 2}}).status_code == 422
    assert authed.put(url, json={"period": "10", "overrides": {"pe": 1000}}).status_code == 422
    r = authed.put(url, json={"period": "15", "overrides": {"pe": 20}})
    assert r.status_code == 200 and r.json()["saved_period"] == "15" and r.json()["multiples"]["pe"] == 20
    eps = [y["eps"] for y in r.json()["years"] if y["eps"] is not None][-1]
    assert abs(r.json()["fv_std"] - 20 * eps) < 1e-3
    assert authed.put(url, json={"period": "10", "overrides": {}}).json()["overrides"] == {}
    assert authed.get("/api/instruments/999999/fairvalue").status_code == 404
    summ = authed.get(f"/api/instruments/{iid}/fairvalue/summary").json()
    assert summ["available"] and summ["fv_std"] and len(summ["bands"]) == 11 and "prices" not in summ
    btc = _wait_for(authed, "BTC")["id"]
    assert authed.get(f"/api/instruments/{btc}/fairvalue/summary").json() == {"available": False}


def test_fair_value_requires_auth(client: httpx.Client) -> None:
    assert client.get("/api/instruments/1/fairvalue").status_code == 401
    assert client.get("/api/instruments/1/fairvalue/summary").status_code == 401
    assert client.put("/api/instruments/1/fairvalue/settings", json={}).status_code in (401, 403)
