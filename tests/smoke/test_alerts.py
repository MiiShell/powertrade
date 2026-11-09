"""Phase 6: alert rules, worker evaluation, event history, Telegram delivery (fixture notifier, no network)."""

import time

import httpx

from test_ingestion import _wait_for


def _events(c: httpx.Client, iid: int) -> list[dict]:
    r = c.get("/api/alerts/events", params={"instrument_id": iid})
    assert r.status_code == 200, r.text
    return r.json()["events"]


def test_alerts_require_auth(client: httpx.Client) -> None:
    assert client.get("/api/alerts").status_code == 401
    assert client.get("/api/alerts/events").status_code == 401
    assert client.post("/api/alerts", json={}).status_code in (401, 403)
    assert client.post("/api/alerts/telegram/test").status_code in (401, 403)


def test_alert_validation(authed: httpx.Client) -> None:
    nvda = _wait_for(authed, "NVDA")["id"]
    btc = _wait_for(authed, "BTC")["id"]
    bad = [
        {"instrument_id": nvda, "kind": "price_above", "params": {"price": -1}},
        {"instrument_id": nvda, "kind": "nope", "params": {}},
        {"instrument_id": nvda, "kind": "rsi_above", "params": {"level": 150}},
        {"instrument_id": nvda, "kind": "price_above", "params": {"price": 1}, "cooldown_minutes": -1},
        {"instrument_id": nvda, "kind": "price_above", "params": {"price": 1}, "note": "x" * 201},
        {"instrument_id": btc, "kind": "fv_upside_above", "params": {"pct": 10}},  # stocks only
    ]
    for body in bad:
        assert authed.post("/api/alerts", json=body).status_code == 422, body
    assert authed.post("/api/alerts", json={"instrument_id": 999999, "kind": "price_above",
                                             "params": {"price": 1}}).status_code == 404


def test_alert_fires_once_and_is_delivered(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    body = {"instrument_id": iid, "kind": "price_above", "params": {"price": 0.01}, "note": "Smoke  test",
            "cooldown_minutes": 0}
    r = authed.post("/api/alerts", json=body)
    assert r.status_code == 201, r.text
    rule = r.json()
    assert rule["note"] == "Smoke test" and rule["description"].startswith("Kurs über")
    deadline = time.time() + 60
    while not (evs := [e for e in _events(authed, iid) if e["alert_id"] == rule["id"]]):
        assert time.time() < deadline, "alert did not fire"
        time.sleep(2)
    assert len(evs) == 1 and evs[0]["delivery"] == "sent" and "NVDA" in evs[0]["message"]
    # edge-triggered: re-evaluation (update without change) must not fire again
    assert authed.put(f"/api/alerts/{rule['id']}", json=body).status_code == 200
    time.sleep(4)
    assert len([e for e in _events(authed, iid) if e["alert_id"] == rule["id"]]) == 1
    listed = authed.get("/api/alerts", params={"instrument_id": iid}).json()
    assert any(a["id"] == rule["id"] and a["last_state"] is True for a in listed["alerts"])
    assert listed["telegram"] == "fixture"
    # history: unread -> read
    assert authed.get("/api/alerts/events").json()["unread"] >= 1
    assert authed.post("/api/alerts/events/read").json()["marked"] >= 1
    assert authed.get("/api/alerts/events").json()["unread"] == 0
    # delete keeps the history entry
    assert authed.delete(f"/api/alerts/{rule['id']}").status_code == 204
    assert authed.delete(f"/api/alerts/{rule['id']}").status_code == 404
    assert any(e["message"].startswith("🔔 NVDA") for e in _events(authed, iid))


def test_ma_cross_does_not_fire_on_creation(authed: httpx.Client) -> None:
    iid = _wait_for(authed, "NVDA")["id"]
    body = {"instrument_id": iid, "kind": "ma_cross_above", "params": {"ma": "sma", "period": 20}}
    rule = authed.post("/api/alerts", json=body).json()
    deadline = time.time() + 60
    while (a := next(x for x in authed.get("/api/alerts").json()["alerts"] if x["id"] == rule["id"]))[
        "last_evaluated_at"
    ] is None:
        assert time.time() < deadline, "not evaluated"
        time.sleep(2)
    assert a["last_state"] is not None
    assert not [e for e in _events(authed, iid) if e["alert_id"] == rule["id"]]
    assert authed.delete(f"/api/alerts/{rule['id']}").status_code == 204


def test_telegram_test_message(authed: httpx.Client) -> None:
    r = authed.post("/api/alerts/telegram/test")
    assert r.status_code == 200 and r.json()["status"] in ("sent", "already requested this minute")
