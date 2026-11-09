"""Market data provider adapters. Hosts are fixed; provider symbols are validated before use (no SSRF)."""

import asyncio
import csv
import hashlib
import io
import random
import re
import time as _time
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.market.bars import Bar, day_ts
from app.market.budget import BudgetExceeded, DailyBudget

SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-=^_]{1,32}$")
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class ProviderError(Exception):
    """Provider failed (network, HTTP status, payload). Message is safe to store."""


class ProviderHTTPError(ProviderError):
    def __init__(self, provider: str, status: int) -> None:
        super().__init__(f"{provider}: HTTP {status}")
        self.status = status


class Provider(Protocol):
    name: str

    async def daily(self, symbol: str, start: date | None) -> list[Bar]: ...


def validate_symbol(symbol: str) -> str:
    if not SYMBOL_RE.fullmatch(symbol):
        raise ProviderError("invalid provider symbol")
    return symbol


class _HttpProvider:
    name = "http"
    min_interval_s = 0.5
    max_bytes = MAX_RESPONSE_BYTES

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def _get(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> bytes:
        async with self._lock:  # simple per-provider rate limit
            wait = self.min_interval_s - (_time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = _time.monotonic()
        try:
            async with self._client.stream("GET", url, params=params, headers=headers) as r:
                if r.status_code != 200:
                    raise ProviderHTTPError(self.name, r.status_code)
                chunks: list[bytes] = []
                size = 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ProviderError(f"{self.name}: response too large")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: {type(exc).__name__}") from exc


class YahooProvider(_HttpProvider):
    name = "yahoo"
    url = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    async def daily(self, symbol: str, start: date | None) -> list[Bar]:
        sym = quote(validate_symbol(symbol), safe="")
        p1 = int(day_ts(start).timestamp()) if start else 0
        params = {
            "period1": p1,
            "period2": int(datetime.now(UTC).timestamp()) + 86400,
            "interval": "1d",
            "includeAdjustedClose": "true",
            "events": "div,split",
        }
        raw = await self._get(self.url.format(symbol=sym), params)
        return parse_yahoo(raw)

    async def splits(self, symbol: str) -> list[tuple[date, float]]:
        """Full split history (monthly bars keep the payload small)."""
        sym = quote(validate_symbol(symbol), safe="")
        params = {
            "period1": 0,
            "period2": int(datetime.now(UTC).timestamp()),
            "interval": "1mo",
            "events": "split",
        }
        return parse_yahoo_splits(await self._get(self.url.format(symbol=sym), params))


def parse_yahoo_splits(raw: bytes) -> list[tuple[date, float]]:
    """Split events from a Yahoo chart payload -> [(ex_date, ratio numerator/denominator)]."""
    import json

    try:
        res = json.loads(raw)["chart"]["result"][0]
        splits = (res.get("events") or {}).get("splits") or {}
    except (KeyError, IndexError, TypeError, ValueError):
        return []
    out: list[tuple[date, float]] = []
    for ev in splits.values():
        try:
            num, den = float(ev["numerator"]), float(ev["denominator"])
            if num > 0 and den > 0 and num != den:
                out.append((datetime.fromtimestamp(int(ev["date"]), UTC).date(), num / den))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def parse_yahoo(raw: bytes) -> list[Bar]:
    import json

    try:
        data = json.loads(raw)
        chart = data["chart"]
        if chart.get("error"):
            raise ProviderError(f"yahoo: {str(chart['error'].get('code', 'error'))[:64]}")
        res = chart["result"][0]
        stamps: list[int] = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or [None] * len(stamps)
        offset = int(res["meta"].get("gmtoffset") or 0)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ProviderError("yahoo: unexpected payload") from exc
    bars: list[Bar] = []
    for i, t in enumerate(stamps):
        o, h, lo, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, lo, c):
            continue
        local_day = datetime.fromtimestamp(t + offset, UTC).date()
        bars.append(Bar(day_ts(local_day), o, h, lo, c, adj[i], q.get("volume", [None] * len(stamps))[i]))
    return bars


class StooqProvider(_HttpProvider):
    name = "stooq"
    url = "https://stooq.com/q/d/l/"

    async def daily(self, symbol: str, start: date | None) -> list[Bar]:
        params: dict[str, Any] = {"s": validate_symbol(symbol).lower(), "i": "d"}
        if start:
            params["d1"] = start.strftime("%Y%m%d")
            params["d2"] = datetime.now(UTC).strftime("%Y%m%d")
        return parse_stooq(await self._get(self.url, params))


def parse_stooq(raw: bytes) -> list[Bar]:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text or text.lower().startswith(("no data", "exceeded")):
        return []
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "Close" not in reader.fieldnames:
        raise ProviderError("stooq: unexpected payload")
    bars: list[Bar] = []
    for row in reader:
        try:
            d = date.fromisoformat(row["Date"])
            vol = float(row["Volume"]) if row.get("Volume") else None
            bars.append(
                Bar(
                    day_ts(d),
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    None,
                    vol,
                )
            )
        except (KeyError, ValueError):
            continue
    return bars


class KrakenProvider(_HttpProvider):
    """Crypto OHLC. Public API returns max. 720 candles (~2 years daily)."""

    name = "kraken"
    url = "https://api.kraken.com/0/public/OHLC"
    min_interval_s = 1.0

    async def daily(self, symbol: str, start: date | None) -> list[Bar]:
        params: dict[str, Any] = {"pair": validate_symbol(symbol), "interval": 1440}
        if start:
            params["since"] = int(day_ts(start).timestamp())
        return parse_kraken(await self._get(self.url, params))


def parse_kraken(raw: bytes) -> list[Bar]:
    import json

    try:
        data = json.loads(raw)
        if data.get("error"):
            raise ProviderError(f"kraken: {str(data['error'][0])[:64]}")
        rows = next(v for k, v in data["result"].items() if k != "last")
        return [
            Bar(
                day_ts(datetime.fromtimestamp(int(r[0]), UTC).date()),
                float(r[1]),
                float(r[2]),
                float(r[3]),
                float(r[4]),
                None,
                float(r[6]),
            )
            for r in rows
        ]
    except (KeyError, IndexError, TypeError, ValueError, StopIteration) as exc:
        raise ProviderError("kraken: unexpected payload") from exc


class FmpProvider(_HttpProvider):
    """Financial Modeling Prep (stable API). Key sent as header (never in URL/logs).

    Free plan: 250 calls/day, ~5 years EOD history, 500 MB/30 days -> every call goes through DailyBudget.
    """

    name = "fmp"
    url = "https://financialmodelingprep.com/stable/historical-price-eod/full"
    max_history_days = 5 * 365

    def __init__(self, client: httpx.AsyncClient, api_key: str, budget: "DailyBudget | None") -> None:
        super().__init__(client)
        self._key = api_key
        self._budget = budget

    async def daily(self, symbol: str, start: date | None) -> list[Bar]:
        if not self._key:
            raise ProviderError("fmp: no api key configured")
        sym = validate_symbol(symbol)
        today = datetime.now(UTC).date()
        frm = max(start or date.min, today - timedelta(days=self.max_history_days))
        if self._budget is not None:
            try:
                await self._budget.acquire()
            except BudgetExceeded as exc:
                raise ProviderError(f"fmp: {exc}") from exc
        try:
            raw = await self._get(
                self.url,
                {"symbol": sym, "from": frm.isoformat(), "to": today.isoformat()},
                headers={"apikey": self._key},
            )
        except ProviderHTTPError as exc:
            if exc.status == 429 and self._budget is not None:
                await self._budget.block_today()
            if exc.status in (401, 403):
                raise ProviderError("fmp: unauthorized (check api key)") from exc
            if exc.status == 402:
                raise ProviderError("fmp: symbol/endpoint not in current plan") from exc
            raise
        if self._budget is not None:
            await self._budget.record_bytes(len(raw))
        return parse_fmp(raw)

    base = "https://financialmodelingprep.com/stable/"
    ENDPOINTS = frozenset(
        {"profile", "income-statement", "balance-sheet-statement", "cash-flow-statement", "dividends"}
    )

    async def profile_raw(self, symbol: str) -> bytes:
        """Raw profile JSON (cleaned by app.market.profile). Budgeted like every FMP call."""
        return await self.get_raw("profile", symbol)

    async def get_raw(self, endpoint: str, symbol: str, **params: Any) -> bytes:
        """Budgeted GET of an allow-listed FMP stable endpoint for one validated symbol."""
        if endpoint not in self.ENDPOINTS:
            raise ProviderError("fmp: endpoint not allowed")
        if not self._key:
            raise ProviderError("fmp: no api key configured")
        sym = validate_symbol(symbol)
        if self._budget is not None:
            try:
                await self._budget.acquire()
            except BudgetExceeded as exc:
                raise ProviderError(f"fmp: {exc}") from exc
        try:
            raw = await self._get(
                self.base + endpoint, {"symbol": sym, **params}, headers={"apikey": self._key}
            )
        except ProviderHTTPError as exc:
            if exc.status == 429 and self._budget is not None:
                await self._budget.block_today()
            if exc.status in (401, 403):
                raise ProviderError("fmp: unauthorized (check api key)") from exc
            if exc.status == 402:
                raise ProviderError("fmp: symbol/endpoint not in current plan") from exc
            raise
        if self._budget is not None:
            await self._budget.record_bytes(len(raw))
        return raw


def parse_fmp(raw: bytes) -> list[Bar]:
    import json

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProviderError("fmp: unexpected payload") from exc
    if isinstance(data, dict):
        if "Error Message" in data:
            raise ProviderError(f"fmp: {str(data['Error Message'])[:80]}")
        data = data.get("historical", [])  # legacy v3 shape
    if not isinstance(data, list):
        raise ProviderError("fmp: unexpected payload")
    bars: list[Bar] = []
    for row in data:
        try:
            bars.append(
                Bar(
                    day_ts(date.fromisoformat(str(row["date"])[:10])),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["adjClose"]) if row.get("adjClose") is not None else None,
                    float(row["volume"]) if row.get("volume") is not None else None,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return bars


class SecProvider(_HttpProvider):
    """SEC EDGAR (official, free). Fair-access policy: identify with contact e-mail, <= 10 requests/s."""

    name = "sec"
    min_interval_s = 0.25
    max_bytes = 80 * 1024 * 1024  # companyfacts of large filers can be tens of MB
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    facts_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

    def __init__(self, client: httpx.AsyncClient, contact: str) -> None:
        super().__init__(client)
        self._headers = {"User-Agent": f"PowerTrade/0.1 {contact}", "Accept": "application/json"}
        self.enabled = bool(contact)

    async def ticker_map(self) -> dict[str, int]:
        import json

        if not self.enabled:
            raise ProviderError("sec: no contact configured (PT_SEC_CONTACT)")
        try:
            data = json.loads(await self._get(self.tickers_url, headers=self._headers))
            return {str(v["ticker"]).upper(): int(v["cik_str"]) for v in data.values()}
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProviderError("sec: unexpected ticker payload") from exc

    async def companyfacts(self, cik: int) -> dict[str, Any]:
        import json

        if not self.enabled:
            raise ProviderError("sec: no contact configured (PT_SEC_CONTACT)")
        if not 0 < cik < 10**10:
            raise ProviderError("sec: invalid cik")
        try:
            data = json.loads(await self._get(self.facts_url.format(cik=cik), headers=self._headers))
        except ValueError as exc:
            raise ProviderError("sec: unexpected payload") from exc
        if not isinstance(data, dict):
            raise ProviderError("sec: unexpected payload")
        return data


class FixtureProvider:
    """Deterministic synthetic data for tests (no network)."""

    name = "fixture"
    enabled = True

    async def ticker_map(self) -> dict[str, int]:
        return {"NVDA": 1045810, "MSFT": 789019}

    async def splits(self, symbol: str) -> list[tuple[date, float]]:
        validate_symbol(symbol)
        return [(date(2021, 7, 20), 4.0)] if symbol == "NVDA" else []

    async def companyfacts(self, cik: int) -> dict[str, Any]:
        """12 fiscal years of synthetic, steadily growing facts in EDGAR companyfacts shape."""

        def entries(vals: list[float], instant: bool = False) -> list[dict[str, Any]]:
            out = []
            for i, v in enumerate(vals):
                y = 2014 + i
                e: dict[str, Any] = {
                    "end": f"{y}-12-31",
                    "val": v,
                    "form": "10-K",
                    "fp": "FY",
                    "filed": f"{y + 1}-02-15",
                    "fy": y,
                }
                if not instant:
                    e["start"] = f"{y}-01-01"
                out.append(e)
            return out

        n = 12
        # as-reported per-share values: filings before the 4:1 split (2021-07-20) are on the old share basis
        pre = [4.0 if 2014 + i <= 2020 else 1.0 for i in range(n)]
        eps = [1.0 * 1.12**i * pre[i] for i in range(n)]
        g = {
            "Revenues": {"units": {"USD": entries([1e10 * 1.1**i for i in range(n)])}},
            "NetIncomeLoss": {"units": {"USD": entries([1e9 * 1.12**i for i in range(n)])}},
            "EarningsPerShareDiluted": {"units": {"USD/shares": entries(eps)}},
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {"USD": entries([1.5e9 * 1.1**i for i in range(n)])}
            },
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": entries([3e8] * n)}},
            "CommonStockDividendsPerShareDeclared": {
                "units": {"USD/shares": entries([0.3 * 1.08**i * pre[i] for i in range(n)])}
            },
            "LongTermDebt": {"units": {"USD": entries([2e9] * n, instant=True)}},
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": entries([1e9] * n, instant=True)}},
            "StockholdersEquity": {
                "units": {"USD": entries([5e9 * 1.05**i for i in range(n)], instant=True)}
            },
        }
        return {"cik": cik, "entityName": "Fixture Corp", "facts": {"us-gaap": g}}

    async def profile_raw(self, symbol: str) -> bytes:
        import json

        validate_symbol(symbol)
        return json.dumps(
            [
                {
                    "companyName": f"{symbol} Test Corp",
                    "description": "Synthetic profile  for\ttests.",
                    "sector": "Technology",
                    "industry": "Software",
                    "country": "US",
                    "exchange": "NASDAQ",
                    "currency": "USD",
                    "website": "https://example.com",
                    "ceo": "Jane Doe",
                    "fullTimeEmployees": "1234",
                    "ipoDate": "2000-01-31",
                    "isin": "US0000000002",
                    "marketCap": 1.5e12,
                    "beta": 1.2,
                    "lastDividend": 0.5,
                    "averageVolume": 1e6,
                    "isEtf": False,
                }
            ]
        ).encode()

    def __init__(self, crypto_symbols: set[str] | None = None) -> None:
        self._crypto = crypto_symbols or set()

    async def daily(self, symbol: str, start: date | None) -> list[Bar]:
        validate_symbol(symbol)
        seed = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:8], "big")
        rng = random.Random(seed)  # noqa: S311 - test data only
        d, end = date(2015, 1, 1), datetime.now(UTC).date()
        price: float = 10.0 + seed % 500
        bars: list[Bar] = []
        while d <= end:
            if d.weekday() < 5 or symbol in self._crypto:
                o = price
                c = max(0.5, o * (1 + rng.gauss(0.0004, 0.02)))
                h, lo = max(o, c) * (1 + abs(rng.gauss(0, 0.005))), min(o, c) * (1 - abs(rng.gauss(0, 0.005)))
                vol = float(rng.randint(1_000, 1_000_000))  # always consume RNG -> stable series
                if start is None or d >= start:
                    bars.append(Bar(day_ts(d), o, h, lo, c, c, vol))
                price = c
            d += timedelta(days=1)
        return bars


def build_providers(
    mode: str,
    user_agent: str,
    fmp_api_key: str = "",
    fmp_budget: DailyBudget | None = None,
    sec_contact: str = "",
) -> tuple[dict[str, Provider], httpx.AsyncClient | None]:
    if mode == "fixture":
        fx = FixtureProvider()
        return {"yahoo": fx, "stooq": fx, "kraken": fx, "fmp": fx, "sec": fx}, None
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": user_agent, "Accept": "application/json,text/csv,*/*"},
        follow_redirects=False,
        limits=httpx.Limits(max_connections=10),
    )
    return {
        "yahoo": YahooProvider(client),
        "stooq": StooqProvider(client),
        "kraken": KrakenProvider(client),
        "fmp": FmpProvider(client, fmp_api_key, fmp_budget),
        "sec": SecProvider(client, sec_contact),  # type: ignore[dict-item]
    }, client
