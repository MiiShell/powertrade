"""Phase 1: market data pipeline (fixture provider, no network). Runs before test_smoke.py (alphabetical)."""

import time

import httpx


def _wait_for(c: httpx.Client, symbol: str, timeout: float = 90) -> dict:
    deadline = time.time() + timeout
    while True:
        items = {i["symbol"]: i for i in c.get("/api/watchlist").json()["items"]}
        item = items.get(symbol)
        if item and item["ingestion"]["status"] in ("success", "failed"):
            return item
        assert time.time() < deadline, f"ingestion for {symbol} did not finish: {item}"
        time.sleep(2)


def test_market_endpoints_require_auth(client: httpx.Client) -> None:
    assert client.get("/api/watchlist").status_code == 401
    assert client.get("/api/instruments/1/bars").status_code == 401
    assert client.post("/api/watchlist/items", json={"symbol": "X", "type": "stock"}).status_code == 401


def test_seeded_watchlist_ingested(authed: httpx.Client) -> None:
    symbols = [i["symbol"] for i in authed.get("/api/watchlist").json()["items"]]
    assert symbols == ["NVDA", "BTC", "ETH", "SOL", "XMR", "GOLD", "SILVER"]
    item = _wait_for(authed, "NVDA")
    assert item["ingestion"]["status"] == "success", item
    assert item["last_close"] and item["last_close"] > 0
    assert item["change_pct"] is not None


def test_daily_and_weekly_bars(authed: httpx.Client) -> None:
    item = _wait_for(authed, "BTC")
    iid = item["id"]
    d = authed.get(f"/api/instruments/{iid}/bars", params={"tf": "1d", "limit": 10000}).json()
    bars = d["bars"]
    assert d["columns"] == ["t", "o", "h", "l", "c", "v"]
    assert len(bars) > 2500
    ts = [b[0] for b in bars]
    assert ts == sorted(ts) and len(ts) == len(set(ts))
    assert all(b[2] >= max(b[1], b[4]) and b[3] <= min(b[1], b[4]) and b[3] > 0 for b in bars)

    w = authed.get(f"/api/instruments/{iid}/bars", params={"tf": "1w", "limit": 10000}).json()["bars"]
    assert len(bars) / 6 < len(w) < len(bars) / 4
    # weekly buckets start on Monday 00:00 UTC
    assert all(time.gmtime(b[0]).tm_wday == 0 and b[0] % 86400 == 0 for b in w)

    ranged = authed.get(
        f"/api/instruments/{iid}/bars", params={"tf": "1d", "start": "2024-01-01", "end": "2024-01-31"}
    ).json()["bars"]
    assert 15 <= len(ranged) <= 23


def test_add_refresh_idempotent_remove(authed: httpx.Client) -> None:
    r = authed.post(
        "/api/watchlist/items", json={"symbol": "sap.de", "type": "stock", "currency": "eur", "name": "SAP"}
    )
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    assert r.json()["sources"][0] == {"provider": "yahoo", "symbol": "SAP.DE", "priority": 1}
    _wait_for(authed, "SAP.DE")
    before = authed.get(f"/api/instruments/{iid}/bars", params={"limit": 10000}).json()["bars"]

    assert authed.post(f"/api/instruments/{iid}/refresh").status_code == 202
    time.sleep(5)
    after = authed.get(f"/api/instruments/{iid}/bars", params={"limit": 10000}).json()["bars"]
    assert len(after) == len(before)  # upsert, no duplicates

    runs = authed.get("/api/ingestion/runs", params={"limit": 100}).json()["runs"]
    assert any(r["symbol"] == "SAP.DE" and r["status"] == "success" for r in runs)

    assert authed.delete(f"/api/watchlist/items/{iid}").status_code == 204
    assert authed.delete(f"/api/watchlist/items/{iid}").status_code == 404
    assert "SAP.DE" not in [i["symbol"] for i in authed.get("/api/watchlist").json()["items"]]


def test_input_validation(authed: httpx.Client) -> None:
    bad = [
        {"symbol": "../etc/passwd", "type": "stock"},
        {"symbol": "OK", "type": "weird"},
        {"symbol": "OK", "type": "stock", "currency": "EURO"},
        {"symbol": "OK", "type": "stock", "sources": [{"provider": "evil.com", "symbol": "x"}]},
        {"symbol": "OK", "type": "stock", "sources": [{"provider": "yahoo", "symbol": "a/b"}]},
    ]
    for body in bad:
        assert authed.post("/api/watchlist/items", json=body).status_code == 422, body
    assert authed.get("/api/instruments/1/bars", params={"tf": "1m"}).status_code == 422
    assert authed.get("/api/instruments/1/bars", params={"limit": 999999}).status_code == 422
    assert authed.get("/api/instruments/999999/bars").status_code == 404


def test_fmp_source_and_usage(authed: httpx.Client) -> None:
    r = authed.post("/api/watchlist/items", json={"symbol": "MSFT", "type": "stock"})
    assert r.status_code == 201
    assert [s["provider"] for s in r.json()["sources"]] == ["yahoo", "fmp"]
    usage = authed.get("/api/providers/usage").json()["fmp"]
    assert usage["configured"] is False  # test deploy has no key
    assert usage["daily_limit"] == 240
    assert 0 < usage["allowed_now"] <= usage["daily_limit"]
    assert authed.delete(f"/api/watchlist/items/{r.json()['id']}").status_code == 204


def test_chart_indicators(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    r = authed.get(
        f"/api/instruments/{iid}/chart",
        params={"tf": "1d", "limit": 500, "sma": "20,200", "ema": "21", "rsi": 14},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["bars"]) == 500
    assert set(d["indicators"]) == {"sma20", "sma200", "ema21"}
    # warm-up history is fetched, so even SMA200 covers the whole window
    assert len(d["indicators"]["sma200"]) == 500
    assert d["indicators"]["sma20"][-1][0] == d["bars"][-1][0]
    rsi = d["rsi"]
    assert rsi["period"] == 14 and len(rsi["values"]) == 500
    assert all(0 <= v <= 100 for _, v in rsi["values"])
    for div in rsi["divergences"]:
        assert div["kind"] in ("bull", "bear") and div["prev_t"] < div["t"]
    w = authed.get(
        f"/api/instruments/{iid}/chart", params={"tf": "1w", "rsi": 0, "sma": "", "ema": ""}
    ).json()
    assert w["rsi"] is None and w["indicators"] == {} and len(w["bars"]) > 100


def test_chart_validation(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    for params in (
        {"sma": "1"},
        {"sma": "x"},
        {"ema": "1,2,3,4,5,6,7,8"},
        {"rsi": 500},
        {"tf": "4h"},
        {"sma": "999"},
    ):
        assert authed.get(f"/api/instruments/{iid}/chart", params=params).status_code == 422, params
    assert authed.get("/api/instruments/999999/chart").status_code == 404


def test_levels_crud(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    r = authed.post(
        f"/api/instruments/{iid}/levels", json={"price": 123.45, "color": "#f85149", "label": "R1"}
    )
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    levels = authed.get(f"/api/instruments/{iid}/chart", params={"limit": 10}).json()["levels"]
    assert {"id": lid, "price": 123.45, "color": "#f85149", "label": "R1"} in levels
    for bad in (
        {"price": -1},
        {"price": 10, "color": "red"},
        {"price": 10, "color": "#fff;x"},
        {"price": 10, "label": "x" * 41},
    ):
        assert authed.post(f"/api/instruments/{iid}/levels", json=bad).status_code == 422, bad
    assert authed.delete(f"/api/instruments/{iid}/levels/{lid}").status_code == 204
    assert authed.delete(f"/api/instruments/{iid}/levels/{lid}").status_code == 404
    assert authed.delete(f"/api/instruments/999999/levels/{lid}").status_code == 404
