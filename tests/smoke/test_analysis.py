"""Phase 7: Claude chart analysis (fixture analyzer, no network): validation, worker flow, cost log, budget."""

import base64
import struct
import time
import zlib

import httpx

from test_ingestion import _wait_for


def _png(w: int = 600, h: int = 300) -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\x20\x20\x20" * w for _ in range(h))
    img = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(img).decode()


def test_analysis_requires_auth(client: httpx.Client) -> None:
    assert client.get("/api/ai/usage").status_code == 401
    assert client.get("/api/analyses/1").status_code == 401
    assert client.post("/api/instruments/1/analysis", json={}).status_code in (401, 403)


def test_analysis_validation(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    url = f"/api/instruments/{iid}/analysis"
    assert authed.post(url, json={"image": "x" * 200}).status_code == 422  # not base64 PNG
    gif = base64.b64encode(b"GIF89a" + b"\x00" * 200).decode()
    assert authed.post(url, json={"image": gif}).status_code == 422
    assert authed.post(url, json={"image": _png(50, 50)}).status_code == 422  # too small
    assert authed.post(url, json={"image": _png(), "model": "gpt-4"}).status_code == 422
    assert authed.post(url, json={"image": _png(), "tf": "1h"}).status_code == 422
    assert authed.post("/api/instruments/999999/analysis", json={"image": _png()}).status_code == 404


def test_analysis_flow_and_cost_log(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    before = authed.get("/api/ai/usage").json()
    assert before["analyzer"] == "fixture" and before["default_model"] == "claude-opus-5-5"
    assert set(before["models"]) == {"claude-opus-5-5", "claude-sonnet-5-5"}
    r = authed.post(f"/api/instruments/{iid}/analysis", json={"image": _png(), "model": "claude-sonnet-5-5"})
    assert r.status_code == 202, r.text
    aid = r.json()["id"]
    deadline = time.time() + 60
    while (a := authed.get(f"/api/analyses/{aid}").json())["status"] in ("queued", "running"):
        assert time.time() < deadline, "analysis did not finish"
        time.sleep(1)
    assert a["status"] == "done", a
    res = a["result"]
    assert res["trend"]["direction"] in ("up", "down", "sideways") and len(res["scenarios"]) == 3
    assert a["cost_usd"] > 0 and a["model_served"] == "claude-sonnet-5-5" and a["reserved_usd"] == 0
    assert "context" not in a
    ctx = authed.get(f"/api/analyses/{aid}", params={"context": "true"}).json()["context"]
    assert ctx["instrument"]["symbol"] == "NVDA" and len(ctx["bars"]["rows"]) <= 150
    assert ctx["indicators_last"]["sma200"] is not None and "fair_value" in ctx
    hist = authed.get(f"/api/instruments/{iid}/analyses").json()["analyses"]
    assert hist[0]["id"] == aid and hist[0]["confidence"] == "medium"
    after = authed.get("/api/ai/usage").json()
    assert after["spent_month_usd"] > before["spent_month_usd"]
    assert after["analyses_today"] == before["analyses_today"] + 1
    assert authed.get("/api/analyses/999999").status_code == 404


def test_crypto_analysis_without_fair_value(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "BTC")["id"]
    r = authed.post(f"/api/instruments/{iid}/analysis", json={"image": _png(), "tf": "1w"})
    assert r.status_code == 202, r.text
    ctx = authed.get(f"/api/analyses/{r.json()['id']}", params={"context": "true"}).json()["context"]
    assert ctx["timeframe"] == "weekly" and "fair_value" not in ctx
