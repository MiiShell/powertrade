import json
from datetime import UTC, date, datetime

import fakeredis
import httpx
import pytest

from app.market.bars import day_ts
from app.market.budget import BudgetExceeded, DailyBudget
from app.market.providers import FmpProvider, ProviderError, parse_fmp

ROWS = [
    {
        "symbol": "NVDA",
        "date": "2026-11-06",
        "open": 182.5,
        "high": 186,
        "low": 181,
        "close": 185.5,
        "volume": 2000,
        "change": 3,
        "vwap": 184,
    },
    {
        "symbol": "NVDA",
        "date": "2026-11-05",
        "open": 180,
        "high": 184,
        "low": 179,
        "close": 183,
        "volume": 1000,
    },
]


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis()


def at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 11, 9, h, m, tzinfo=UTC)


def test_parse_fmp_shapes() -> None:
    bars = parse_fmp(json.dumps(ROWS).encode())
    assert sorted(b.ts for b in bars) == [day_ts(date(2026, 11, 5)), day_ts(date(2026, 11, 6))]
    legacy = parse_fmp(json.dumps({"symbol": "NVDA", "historical": ROWS}).encode())
    assert len(legacy) == 2
    with pytest.raises(ProviderError, match="Invalid API KEY"):
        parse_fmp(json.dumps({"Error Message": "Invalid API KEY."}).encode())
    with pytest.raises(ProviderError):
        parse_fmp(b"<html>")


def test_pacing_cap() -> None:
    b = DailyBudget(fakeredis.FakeAsyncRedis(), "t", daily_limit=240, burst=20, bandwidth_bytes_30d=10**9)
    assert b.cap_now(at(0)) == 20
    assert b.cap_now(at(12)) == 140
    assert b.cap_now(at(23, 59)) == 240  # capped at daily limit


async def test_acquire_respects_pacing_and_daily_reset(redis: fakeredis.FakeAsyncRedis) -> None:
    b = DailyBudget(redis, "t", daily_limit=240, burst=3, bandwidth_bytes_30d=10**9)
    for _ in range(3):
        await b.acquire(at(0, 1))
    with pytest.raises(BudgetExceeded, match="paced"):
        await b.acquire(at(0, 2))
    assert await b.acquire(at(6)) == 4  # allowance grew during the day
    assert await b.acquire(datetime(2026, 11, 10, 0, 1, tzinfo=UTC)) == 1  # new day


async def test_bandwidth_cap_and_block(redis: fakeredis.FakeAsyncRedis) -> None:
    b = DailyBudget(redis, "t", daily_limit=240, burst=20, bandwidth_bytes_30d=1000)
    await b.record_bytes(600, at(1))
    await b.record_bytes(500, datetime(2026, 10, 20, tzinfo=UTC))  # within 30 days
    with pytest.raises(BudgetExceeded, match="bandwidth"):
        await b.acquire(at(2))

    b2 = DailyBudget(redis, "t2", daily_limit=240, burst=20, bandwidth_bytes_30d=10**9)
    await b2.block_today(at(3))
    with pytest.raises(BudgetExceeded, match="blocked"):
        await b2.acquire(at(4))
    usage = await b2.usage(at(4))
    assert usage["blocked_today"] is True and usage["calls_today"] == 0


async def test_fmp_key_in_header_not_url(redis: fakeredis.FakeAsyncRedis) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=ROWS)

    budget = DailyBudget(redis, "fmp", 240, 20, 10**9)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bars = await FmpProvider(client, "SECRET-KEY", budget).daily("NVDA", date(2026, 11, 1))
    assert len(bars) == 2
    req = seen[0]
    assert req.url.host == "financialmodelingprep.com"
    assert req.headers["apikey"] == "SECRET-KEY"
    assert "SECRET-KEY" not in str(req.url)
    assert req.url.params["from"] == "2026-11-01"
    usage = await budget.usage()
    assert usage["calls_today"] == 1 and usage["bytes_30d"] > 0


async def test_fmp_history_capped_to_5_years(redis: fakeredis.FakeAsyncRedis) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await FmpProvider(client, "k", None).daily("NVDA", None)
    frm = date.fromisoformat(seen[0].url.params["from"])
    assert (datetime.now(UTC).date() - frm).days <= 5 * 365


async def test_fmp_errors(redis: fakeredis.FakeAsyncRedis) -> None:
    status = {"code": 402}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status["code"])

    budget = DailyBudget(redis, "fmp", 240, 20, 10**9)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = FmpProvider(client, "k", budget)
        with pytest.raises(ProviderError, match="not in current plan"):
            await p.daily("SAP.DE", None)
        status["code"] = 401
        with pytest.raises(ProviderError, match="unauthorized"):
            await p.daily("NVDA", None)
        status["code"] = 429
        with pytest.raises(ProviderError, match="429"):
            await p.daily("NVDA", None)
        with pytest.raises(ProviderError, match="blocked"):  # no further request today
            await p.daily("NVDA", None)
        with pytest.raises(ProviderError, match="no api key"):
            await FmpProvider(client, "", budget).daily("NVDA", None)
