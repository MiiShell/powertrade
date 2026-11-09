"""Details page APIs (technicals, pivots, stats, seasonality, profile import).

Runs after test_ingestion.py (alphabetical order)."""

import time

import httpx

from test_ingestion import _wait_for


def _details(c: httpx.Client, iid: int) -> dict:
    r = c.get(f"/api/instruments/{iid}/details")
    assert r.status_code == 200, r.text
    return r.json()


def test_details_requires_auth(client: httpx.Client) -> None:
    assert client.get("/api/instruments/1/details").status_code == 401
    assert client.get("/api/instruments/1/seasonality").status_code == 401


def test_details_technicals_pivots_stats(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    d = _details(authed, iid)
    t = d["technicals"]["1d"]
    assert len(t["oscillators"]["rows"]) == 11 and len(t["moving_averages"]["rows"]) == 15
    assert t["summary"]["label"] in ("strong_buy", "buy", "neutral", "sell", "strong_sell")
    assert sum(t["summary"]["counts"].values()) == 26
    assert d["technicals"]["1w"] is not None and d["technicals"]["1mo"] is not None
    p = d["pivots"]["1d"]
    assert p["basis"].startswith("Monat")
    lv = p["levels"]["classic"]
    assert lv["S3"] < lv["S2"] < lv["S1"] < lv["P"] < lv["R1"] < lv["R2"] < lv["R3"]
    assert d["pivots"]["1w"]["basis"].startswith("Jahr")
    s = d["stats"]
    assert s["range_52w"][0] <= s["price"] <= s["range_52w"][1]
    assert set(s["performance"]) == {"1W", "1M", "3M", "6M", "YTD", "1Y", "5Y"}


def test_technical_snapshots_persisted(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    deadline = time.time() + 60
    while not _details(authed, iid)["rating_history"]:
        assert time.time() < deadline, "no technical snapshot stored"
        time.sleep(2)


def test_profile_imported_and_cleaned(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    deadline = time.time() + 90
    while (p := _details(authed, iid)["profile"]) is None:
        assert time.time() < deadline, "profile not imported"
        time.sleep(2)
    assert p["company_name"] == "NVDA Test Corp"
    assert p["description"] == "Synthetic profile for tests."  # whitespace normalised
    assert p["employees"] == 1234 and p["country"] == "US" and p["isin"] == "US0000000002"
    inst = _details(authed, iid)["instrument"]
    assert inst["isin"] == "US0000000002" and inst["exchange"] == "NASDAQ"  # master data enriched
    r = authed.post(f"/api/instruments/{iid}/profile/refresh")
    assert r.status_code == 202
    assert (
        authed.post(f"/api/instruments/{iid}/profile/refresh").json()["status"] == "already requested today"
    )


def test_seasonality(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "BTC")["id"]
    s = authed.get(f"/api/instruments/{iid}/seasonality").json()
    years = [y["year"] for y in s["years"]]
    assert years == sorted(years) and years[0] == s["range"]["min_year"]
    assert s["average"] and s["average_years"]
    assert all(0 <= d <= 365 for d, _ in s["years"][0]["points"])
    narrow = authed.get(
        f"/api/instruments/{iid}/seasonality", params={"from_year": 2022, "to_year": 2023}
    ).json()
    assert [y["year"] for y in narrow["years"]] == [2022, 2023]
    assert len(narrow["monthly"]) == 2
    bad = authed.get(f"/api/instruments/{iid}/seasonality", params={"from_year": 2024, "to_year": 2020})
    assert bad.status_code == 422
