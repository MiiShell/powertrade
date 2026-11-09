import json
from datetime import UTC, date, datetime

import httpx
import pytest

from app.market.bars import Bar, day_ts, sanitize
from app.market.providers import (
    FixtureProvider,
    ProviderError,
    YahooProvider,
    parse_kraken,
    parse_stooq,
    parse_yahoo,
    validate_symbol,
)
from app.routes.market import InstrumentIn, default_sources

YAHOO = {
    "chart": {
        "result": [
            {
                "meta": {"currency": "USD", "symbol": "NVDA", "gmtoffset": -18000},
                # 2026-11-05 14:30 UTC and 2026-11-06 14:30 UTC (US open), third has nulls
                "timestamp": [1793889000, 1793975400, 1794234600],
                "indicators": {
                    "quote": [
                        {
                            "open": [180.0, 182.5, None],
                            "high": [184.0, 186.0, None],
                            "low": [179.0, 181.0, None],
                            "close": [183.0, 185.5, None],
                            "volume": [1000, 2000, None],
                        }
                    ],
                    "adjclose": [{"adjclose": [182.9, 185.4, None]}],
                },
            }
        ],
        "error": None,
    }
}


def test_parse_yahoo() -> None:
    bars = parse_yahoo(json.dumps(YAHOO).encode())
    assert len(bars) == 2
    assert bars[0].ts == day_ts(date(2026, 11, 5))
    assert bars[1].close == 185.5 and bars[1].adj_close == 185.4 and bars[1].volume == 2000


def test_parse_yahoo_error() -> None:
    raw = json.dumps({"chart": {"result": None, "error": {"code": "Not Found", "description": "x"}}}).encode()
    with pytest.raises(ProviderError, match="Not Found"):
        parse_yahoo(raw)
    with pytest.raises(ProviderError):
        parse_yahoo(b"<html>")


def test_parse_stooq() -> None:
    raw = (
        b"Date,Open,High,Low,Close,Volume\n2026-11-05,180,184,179,183,1000\n2026-11-06,182.5,186,181,185.5,\n"
    )
    bars = parse_stooq(raw)
    assert [b.close for b in bars] == [183.0, 185.5]
    assert bars[1].volume is None
    assert parse_stooq(b"No data") == []
    with pytest.raises(ProviderError):
        parse_stooq(b"foo,bar\n1,2")


def test_parse_kraken() -> None:
    raw = json.dumps(
        {
            "error": [],
            "result": {
                "XXBTZUSD": [[1793923200, "75000.1", "76000", "74000", "75500", "75200", "123.4", 999]],
                "last": 1793923200,
            },
        }
    ).encode()
    bars = parse_kraken(raw)
    assert bars == [Bar(day_ts(date(2026, 11, 6)), 75000.1, 76000.0, 74000.0, 75500.0, None, 123.4)]
    with pytest.raises(ProviderError, match="Unknown asset pair"):
        parse_kraken(json.dumps({"error": ["EQuery:Unknown asset pair"], "result": {}}).encode())


def test_sanitize() -> None:
    d = day_ts(date(2026, 1, 2))
    bars = [
        Bar(d, 10, 9, 11, 10.5),  # inverted high/low -> repaired
        Bar(day_ts(date(2026, 1, 1)), 10, 11, 9, 10, float("nan"), -5),
        Bar(day_ts(date(2026, 1, 3)), 0, 1, 1, 1),  # non-positive -> dropped
        Bar(day_ts(date(2099, 1, 1)), 1, 1, 1, 1),  # future -> dropped
        Bar(d, 10, 12, 9, 11),  # duplicate day -> last wins
    ]
    out = sanitize(bars, today=date(2026, 6, 1))
    assert [b.ts for b in out] == [day_ts(date(2026, 1, 1)), d]
    assert out[0].adj_close is None and out[0].volume is None
    assert out[1].close == 11 and out[1].high == 12
    fixed = sanitize([Bar(d, 10, 9, 11, 10.5)], today=date(2026, 6, 1))[0]
    assert fixed.high == 11 and fixed.low == 9


@pytest.mark.parametrize("sym", ["NVDA", "BTC-USD", "GC=F", "^GSPC", "nvda.us", "SAP.DE"])
def test_valid_symbols(sym: str) -> None:
    assert validate_symbol(sym) == sym


@pytest.mark.parametrize("sym", ["", "../etc", "a/b", "x?y=1", "http://evil", "A" * 33, "a b", "%2F"])
def test_invalid_symbols(sym: str) -> None:
    with pytest.raises(ProviderError):
        validate_symbol(sym)


async def test_yahoo_rejects_bad_symbol_before_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not be called
        raise AssertionError("request must not be sent")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError):
            await YahooProvider(client).daily("../../admin", None)


async def test_yahoo_http_error_and_url() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="HTTP 429"):
            await YahooProvider(client).daily("GC=F", date(2026, 1, 1))
    assert seen[0].host == "query1.finance.yahoo.com"
    assert seen[0].path == "/v8/finance/chart/GC%3DF" or seen[0].raw_path.startswith(
        b"/v8/finance/chart/GC%3DF"
    )


async def test_fixture_provider_deterministic() -> None:
    p = FixtureProvider()
    a = await p.daily("NVDA", None)
    b = await p.daily("NVDA", date(2026, 1, 1))
    assert len(a) > 2500
    assert a[-len(b) :] == b
    assert all(x.ts.weekday() < 5 for x in a)
    assert a[-1].ts <= day_ts(datetime.now(UTC).date())
    assert sanitize(a) == a


def test_default_sources() -> None:
    assert [(s.provider, s.symbol) for s in default_sources("BTC", "crypto", "USD")] == [
        ("yahoo", "BTC-USD"),
        ("kraken", "XBTUSD"),
    ]
    assert [(s.provider, s.symbol) for s in default_sources("SAP.DE", "stock", "EUR")] == [
        ("yahoo", "SAP.DE"),
        ("fmp", "SAP.DE"),
    ]
    assert [s.provider for s in default_sources("GC=F", "commodity", "USD")] == ["yahoo"]
    assert InstrumentIn(symbol="sap.de", type="stock", currency="eur").symbol == "SAP.DE"
