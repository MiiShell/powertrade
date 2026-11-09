"""Phase 8: Claude stock reports (fixture agent, no network): versioning, charts, number check, Markdown export."""

import time

import httpx

from test_ingestion import _wait_for


def _wait_done(c: httpx.Client, rid: int) -> dict:
    deadline = time.time() + 90
    while (r := c.get(f"/api/reports/{rid}").json())["status"] in ("queued", "running"):
        assert time.time() < deadline, "report did not finish"
        time.sleep(1)
    return r


def test_reports_require_auth(client: httpx.Client) -> None:
    assert client.get("/api/reports").status_code == 401
    assert client.get("/api/reports/1").status_code == 401
    assert client.get("/api/reports/1/markdown").status_code == 401
    assert client.post("/api/instruments/1/reports", json={}).status_code in (401, 403)


def test_report_validation(authed: httpx.Client) -> None:
    btc = _wait_for(authed, "BTC")["id"]
    assert authed.post(f"/api/instruments/{btc}/reports", json={}).status_code == 422  # stocks only
    assert authed.post("/api/instruments/999999/reports", json={}).status_code == 404
    nvda = _wait_for(authed, "NVDA")["id"]
    assert authed.post(f"/api/instruments/{nvda}/reports", json={"model": "gpt-5"}).status_code == 422
    assert authed.get("/api/reports/999999").status_code == 404


def test_report_flow_versions_and_export(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    deadline = time.time() + 120  # fundamentals must be imported first
    while (r := authed.post(f"/api/instruments/{iid}/reports", json={"model": "claude-sonnet-5-5"})).status_code == 422:
        assert time.time() < deadline, r.text
        time.sleep(3)
    assert r.status_code == 202, r.text
    rep = _wait_done(authed, r.json()["id"])
    assert rep["status"] == "done", rep
    assert rep["sections"]["title"].startswith("NVIDIA") and rep["version"] >= 1
    assert set(rep["charts"]) >= {"revenue_earnings", "margins", "per_share", "balance"}
    assert all(v.startswith("data:image/svg+xml;base64,") for v in rep["charts"].values())
    assert rep["sources"][0]["verified"] is True
    assert [w["number"] for w in rep["warnings"]] == ["4.711,0"]  # fixture's invented number is flagged
    assert rep["stats"]["cost_usd"] > 0 and rep["reserved_usd"] == 0
    assert rep["snapshot"]["annual"] and rep["snapshot"]["valuation"]["fv_std"]
    md = authed.get(f"/api/reports/{rep['id']}/markdown")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "attachment" in md.headers["content-disposition"] and md.text.startswith("# NVIDIA")
    # second report -> next version, both listed
    r2 = authed.post(f"/api/instruments/{iid}/reports", json={})
    assert r2.status_code == 202
    rep2 = _wait_done(authed, r2.json()["id"])
    assert rep2["version"] == rep["version"] + 1 and rep2["model"] == "claude-opus-5-5"
    listed = authed.get("/api/reports", params={"instrument_id": iid}).json()
    assert [x["version"] for x in listed["reports"][:2]] == [rep2["version"], rep["version"]]
    assert listed["cost_cap_usd"] == 1.5 and listed["reports"][0]["warnings"] == 1
    usage = authed.get("/api/ai/usage").json()
    assert usage["reports_today"] >= 2 and usage["budget_month_usd"] == 25
