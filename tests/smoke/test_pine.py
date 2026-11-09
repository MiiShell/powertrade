"""Pine scripts (storage API), sandboxed worker delivery/CSP and chart range widgets."""

import httpx

from test_ingestion import _wait_for

V5 = '//@version=5\nindicator("Smoke RSI")\nplot(ta.rsi(close, 14), title="RSI")\nhline(70)\n'


def test_pine_requires_auth(client: httpx.Client) -> None:
    assert client.get("/api/pine/scripts").status_code == 401
    assert client.post("/api/pine/scripts", json={"name": "x", "source": V5}).status_code == 401


def test_builtin_hoss_scripts_seeded_and_protected(authed: httpx.Client) -> None:
    scripts = authed.get("/api/pine/scripts").json()["scripts"]
    builtins = {s["name"]: s for s in scripts if s["builtin"]}
    assert set(builtins) == {"[Hoss] OBV RSI", "[Hoss] VWAP Deviation"}
    obv = builtins["[Hoss] OBV RSI"]
    assert obv["source"].startswith("//@version=5") and "ta.cum(obv_vol)" in obv["source"]
    assert authed.put(f"/api/pine/scripts/{obv['id']}", json={"name": "x", "source": V5}).status_code == 403
    assert authed.delete(f"/api/pine/scripts/{obv['id']}").status_code == 403


def test_pine_crud_and_validation(authed: httpx.Client) -> None:
    r = authed.post("/api/pine/scripts", json={"name": "Smoke  RSI", "source": V5})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["name"] == "Smoke RSI"
    assert authed.post("/api/pine/scripts", json={"name": "Smoke RSI", "source": V5}).status_code == 409
    for bad in (
        {"name": "v4", "source": '//@version=4\nstudy("x")\nplot(close)'},
        {"name": "", "source": V5},
        {"name": "big", "source": V5 + "x" * 100_001},
    ):
        assert authed.post("/api/pine/scripts", json=bad).status_code == 422, bad["name"]
    upd = authed.put(
        f"/api/pine/scripts/{sid}", json={"name": "Smoke RSI 2", "source": V5.replace("14", "7")}
    )
    assert upd.status_code == 200 and "rsi(close, 7)" in upd.json()["source"]
    assert authed.delete(f"/api/pine/scripts/{sid}").status_code == 204
    assert authed.delete(f"/api/pine/scripts/{sid}").status_code == 404


def test_worker_served_with_isolated_csp(client: httpx.Client) -> None:
    w = client.get("/pine-worker.js")
    assert w.status_code == 200
    assert "javascript" in w.headers["content-type"]
    csp = w.headers["content-security-policy"]
    assert "'unsafe-eval'" in csp and "connect-src 'none'" in csp and "default-src 'none'" in csp
    page = client.get("/").headers["content-security-policy"]
    assert "unsafe-eval" not in page and "worker-src 'self'" in page


def test_stats_widgets(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "BTC")["id"]
    s = authed.get(f"/api/instruments/{iid}/stats").json()
    for key in ("day_range", "range_week", "range_52w"):
        lo, hi = s[key]
        assert lo <= s["price"] <= hi, key
    assert s["range_52w"][0] <= s["range_week"][0] and s["range_week"][1] <= s["range_52w"][1]
