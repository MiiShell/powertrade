import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.market import alerts as a
from app.market.notify import (
    FixtureNotifier,
    NotifyError,
    NullNotifier,
    TelegramNotifier,
    build_notifier,
)

TOKEN = "123456789:" + "A" * 35
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


def test_validate_normalises_and_rejects() -> None:
    assert a.validate("price_above", {"price": 200, "junk": 1}) == {"price": 200.0}
    assert a.validate("change_pct", {"pct": -5}) == {"pct": -5.0, "days": 1}
    assert a.validate("ma_cross_above", {}) == {"ma": "sma", "period": 200}
    assert a.validate("rsi_below", {"level": 30}) == {"level": 30.0, "period": 14}
    for kind, params in [
        ("price_above", {"price": -1}),
        ("price_above", {"price": "200"}),
        ("price_above", {"price": True}),
        ("change_pct", {"pct": 0}),
        ("change_pct", {"pct": 5, "days": 1.5}),
        ("ma_cross_below", {"ma": "wma"}),
        ("rsi_above", {"level": 100}),
        ("fv_upside_above", {"pct": 1000}),
        ("nope", {}),
    ]:
        with pytest.raises(ValueError):
            a.validate(kind, params)


def test_conditions() -> None:
    closes = [100.0] * 250 + [110.0]
    assert a.condition("price_above", {"price": 105}, closes, None) == a.Condition(True, 110.0)
    assert a.condition("price_below", {"price": 105}, closes, None).state is False
    c = a.condition("change_pct", {"pct": 5, "days": 1}, closes, None)
    assert c.state is True and c.value == pytest.approx(10.0)
    assert a.condition("change_pct", {"pct": -5, "days": 1}, closes, None).state is False
    assert a.condition("change_pct", {"pct": 5, "days": 400}, closes, None).state is None  # too short
    ma = a.condition("ma_cross_above", {"ma": "sma", "period": 200}, closes, None)
    assert ma.state is True and ma.value == pytest.approx(100.05)
    assert a.condition("ma_cross_below", {"ma": "ema", "period": 200}, closes, None).state is False
    assert a.condition("rsi_above", {"level": 70, "period": 14}, closes, None).state is True
    assert a.condition("fv_upside_above", {"pct": 20}, closes, 30.0) == a.Condition(True, 30.0)
    assert a.condition("fv_upside_above", {"pct": 20}, closes, None).state is None
    assert a.condition("price_above", {"price": 1}, [], None).state is None


def test_edge_trigger_and_cooldown() -> None:
    fire = a.should_fire
    assert fire("price_above", True, None, None, 60, NOW)  # first evaluation, already met
    assert fire("price_above", True, False, None, 60, NOW)  # edge false -> true
    assert not fire("price_above", True, True, None, 60, NOW)  # still met -> no repeat
    assert not fire("price_above", False, False, None, 60, NOW)
    assert not fire("price_above", None, False, None, 60, NOW)
    assert not fire("price_above", True, False, NOW - timedelta(minutes=30), 60, NOW)  # cooldown
    assert fire("price_above", True, False, NOW - timedelta(minutes=61), 60, NOW)
    assert not fire("ma_cross_above", True, None, None, 0, NOW)  # cross: first eval only records
    assert fire("ma_cross_above", True, False, None, 0, NOW)


def test_message_is_plain_text() -> None:
    msg = a.message("NVDA", "USD", "price_above", {"price": 200.0}, 201.5, 201.5, "Nachkauf")
    assert msg.splitlines() == ["🔔 NVDA: Kurs über 200,00", "Kurs 201,50 USD", "Notiz: Nachkauf"]
    msg = a.message("BTC", "USD", "change_pct", {"pct": -5.0, "days": 7}, -6.25, 80000.0, "")
    assert "≤ -5,0 % in 7 T." in msg and "Wert -6,25 %" in msg and "80.000,00" in msg
    assert a.describe("ma_cross_below", {"ma": "ema", "period": 50}) == "Kurs kreuzt EMA50 nach unten"


async def test_telegram_notifier_sends_and_hides_token() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if json.loads(req.content)["text"] == "fail":
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
        return httpx.Response(200, json={"ok": True, "result": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        n = TelegramNotifier(client, TOKEN, "-100123")
        await n.send("hello")
        assert seen[0].url.host == "api.telegram.org" and seen[0].url.path == f"/bot{TOKEN}/sendMessage"
        body = json.loads(seen[0].content)
        assert body == {"chat_id": "-100123", "text": "hello", "disable_web_page_preview": True}
        assert "parse_mode" not in body
        with pytest.raises(NotifyError) as err:
            await n.send("fail")
        assert "chat not found" in str(err.value) and TOKEN not in str(err.value)


async def test_telegram_network_error_has_no_url() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {req.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        with pytest.raises(NotifyError) as err:
            await TelegramNotifier(client, TOKEN, "1").send("x")
    assert str(err.value) == "telegram: ConnectError"


async def test_build_notifier() -> None:
    assert isinstance(build_notifier("fixture", None, "", ""), FixtureNotifier)
    assert isinstance(build_notifier("live", None, TOKEN, "1"), NullNotifier)
    async with httpx.AsyncClient() as client:
        assert not build_notifier("live", client, "", "").configured
        bad = build_notifier("live", client, "not-a-token", "1")
        assert isinstance(bad, NullNotifier) and "not-a-token" not in bad.reason
        assert isinstance(build_notifier("live", client, TOKEN, "42"), TelegramNotifier)
