"""Annual fundamentals import: SEC EDGAR companyfacts (US, long history) with FMP statements as fallback.

All values are cleaned before storage: finite numbers only, annual periods only (330–400 day durations for
flow metrics, fiscal-year-end instants for balance items), one value per metric and fiscal year
(latest filing wins), sign conventions normalised (capex and dividends positive).
"""

import json
import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.market.providers import ProviderError

log = logging.getLogger(__name__)

# metric -> (candidate us-gaap concepts in priority order, unit, kind)
SEC_CONCEPTS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "revenue": (("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                 "RevenueFromContractWithCustomerIncludingAssessedTax"), "USD", "flow"),
    "net_income": (("NetIncomeLoss", "ProfitLoss"), "USD", "flow"),
    "operating_income": (("OperatingIncomeLoss",), "USD", "flow"),
    "eps_diluted": (("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"), "USD/shares", "flow"),
    "shares_diluted": (("WeightedAverageNumberOfDilutedSharesOutstanding",), "shares", "flow"),
    "operating_cf": (("NetCashProvidedByUsedInOperatingActivities",
                      "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"), "USD", "flow"),
    "capex": (("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"), "USD", "flow"),
    "dps": (("CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"), "USD/shares", "flow"),
    "debt": (("LongTermDebt", "LongTermDebtNoncurrent", "DebtInstrumentCarryingAmount"), "USD", "instant"),
    "cash": (("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
             "USD", "instant"),
    "equity": (("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
               "USD", "instant"),
    "assets": (("Assets",), "USD", "instant"),
}
ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "20-F", "40-F"}


@dataclass(frozen=True)
class Fact:
    metric: str
    fiscal_year: int
    period_end: date
    value: float
    unit: str
    source: str
    filed: date | None = None


def fiscal_year_of(end: date) -> int:
    """Fiscal year label: years ending Jan–May belong to the previous calendar year (e.g. NVDA FY ends in Jan)."""
    return end.year if end.month >= 6 else end.year - 1


def _d(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _finite(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def parse_sec_companyfacts(data: dict[str, Any], source: str = "sec") -> list[Fact]:
    gaap = (data.get("facts") or {}).get("us-gaap") or {}
    out: list[Fact] = []
    for metric, (concepts, unit, kind) in SEC_CONCEPTS.items():
        best: dict[int, Fact] = {}
        for concept in concepts:  # earlier concepts win for a given year; later ones only fill gaps
            entries = ((gaap.get(concept) or {}).get("units") or {}).get(unit) or []
            per_year: dict[int, tuple[date, Fact]] = {}
            for e in entries:
                if e.get("form") not in ANNUAL_FORMS:
                    continue
                end, val = _d(e.get("end")), _finite(e.get("val"))
                if end is None or val is None:
                    continue
                if kind == "flow":
                    start = _d(e.get("start"))
                    if start is None or not 330 <= (end - start).days <= 400:
                        continue
                elif e.get("fp") not in ("FY", None):
                    continue
                fy = fiscal_year_of(end)
                filed = _d(e.get("filed")) or date.min
                prev = per_year.get(fy)
                # latest period end within the fiscal year, then latest filing (restatements)
                if prev is None or (end, filed) > (prev[1].period_end, prev[0]):
                    per_year[fy] = (filed, Fact(metric, fy, end, val, unit, source, filed if filed != date.min else None))
            for fy, (_, fact) in per_year.items():
                best.setdefault(fy, fact)
        out.extend(best.values())
    for f in list(out):  # sign conventions
        if f.metric in ("capex", "dps") and f.value < 0:
            out[out.index(f)] = Fact(f.metric, f.fiscal_year, f.period_end, -f.value, f.unit, f.source, f.filed)
    # derived free cash flow
    ocf = {f.fiscal_year: f for f in out if f.metric == "operating_cf"}
    cap = {f.fiscal_year: f for f in out if f.metric == "capex"}
    for fy, o in ocf.items():
        if fy in cap:
            out.append(Fact("free_cf", fy, o.period_end, o.value - cap[fy].value, "USD", source, o.filed))
    return out


# ---------- FMP (fallback, budgeted: 4 calls per stock) ----------
FMP_FIELDS = {
    "income": {"revenue": "revenue", "netIncome": "net_income", "operatingIncome": "operating_income",
               "epsDiluted": "eps_diluted", "epsdiluted": "eps_diluted", "weightedAverageShsOutDil": "shares_diluted"},
    "balance": {"totalDebt": "debt", "cashAndCashEquivalents": "cash", "totalStockholdersEquity": "equity",
                "totalAssets": "assets"},
    "cashflow": {"operatingCashFlow": "operating_cf", "capitalExpenditure": "capex", "freeCashFlow": "free_cf"},
}


def parse_fmp_statement(raw: bytes, kind: str, currency_ok: Iterable[str] = ("USD", "EUR", "GBP", "CHF", "JPY",
                                                                              "CAD", "DKK", "SEK", "NOK", "AUD")
                        ) -> list[Fact]:
    try:
        rows = json.loads(raw)
    except ValueError as exc:
        raise ProviderError("fmp: unexpected payload") from exc
    if isinstance(rows, dict) and "Error Message" in rows:
        raise ProviderError(f"fmp: {str(rows['Error Message'])[:80]}")
    if not isinstance(rows, list):
        raise ProviderError("fmp: unexpected payload")
    out: list[Fact] = []
    for r in rows:
        if not isinstance(r, dict) or r.get("period") not in ("FY", None):
            continue
        end = _d(r.get("date"))
        cur = str(r.get("reportedCurrency") or "USD").upper()
        if end is None or cur not in currency_ok:
            continue
        fy = fiscal_year_of(end)
        for field, metric in FMP_FIELDS[kind].items():
            v = _finite(r.get(field))
            if v is None:
                continue
            if metric == "capex":
                v = abs(v)
            unit = "USD/shares" if metric == "eps_diluted" else "shares" if metric == "shares_diluted" else cur
            out.append(Fact(metric, fy, end, v, unit, "fmp", _d(r.get("filingDate") or r.get("fillingDate"))))
    return out


def parse_fmp_dividends(raw: bytes) -> list[Fact]:
    """Per-payment dividend history -> annual DPS (sum of adjusted dividends per calendar year, full years only)."""
    try:
        rows = json.loads(raw)
    except ValueError as exc:
        raise ProviderError("fmp: unexpected payload") from exc
    if isinstance(rows, dict):
        rows = rows.get("historical", [])
    per_year: dict[int, float] = {}
    for r in rows if isinstance(rows, list) else []:
        d = _d(r.get("date") if isinstance(r, dict) else None)
        v = _finite(r.get("adjDividend") if r.get("adjDividend") is not None else r.get("dividend"))
        if d is None or v is None or v < 0:
            continue
        per_year[d.year] = per_year.get(d.year, 0.0) + v
    this_year = date.today().year
    return [Fact("dps", y, date(y, 12, 31), round(v, 6), "USD/shares", "fmp") for y, v in per_year.items()
            if y < this_year]


# ---------- persistence ----------
UPSERT = text("""
    INSERT INTO fundamental_fact (instrument_id, metric, fiscal_year, period_end, value, unit, source, filed, fetched_at)
    VALUES (:iid, :m, :fy, :end, :v, :u, :src, :filed, now())
    ON CONFLICT (instrument_id, metric, fiscal_year) DO UPDATE SET
        period_end = EXCLUDED.period_end, value = EXCLUDED.value, unit = EXCLUDED.unit,
        source = EXCLUDED.source, filed = EXCLUDED.filed, fetched_at = now()
    WHERE fundamental_fact.source = EXCLUDED.source OR EXCLUDED.source = 'sec'
""")


async def store_facts(engine: AsyncEngine, iid: int, facts: list[Fact]) -> int:
    if not facts:
        return 0
    async with engine.begin() as conn:
        await conn.execute(UPSERT, [
            {"iid": iid, "m": f.metric, "fy": f.fiscal_year, "end": f.period_end, "v": f.value, "u": f.unit,
             "src": f.source, "filed": f.filed} for f in facts
        ])
    return len(facts)


async def record_run(engine: AsyncEngine, iid: int, source: str | None, status: str, facts: int,
                     error: str | None) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO fundamentals_run (instrument_id, source, status, facts, error, finished_at)
            VALUES (:iid, :s, :st, :n, :e, now())
            ON CONFLICT (instrument_id) DO UPDATE SET source = EXCLUDED.source, status = EXCLUDED.status,
              facts = EXCLUDED.facts, error = EXCLUDED.error, finished_at = now()
        """), {"iid": iid, "s": source, "st": status, "n": facts, "e": (error or "")[:500] or None})


async def load_series(engine: AsyncEngine, iid: int) -> dict[str, dict[int, float]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT metric, fiscal_year, value FROM fundamental_fact WHERE instrument_id = :iid "
                 "ORDER BY fiscal_year"), {"iid": iid})
        out: dict[str, dict[int, float]] = {}
        for r in rows:
            out.setdefault(r.metric, {})[r.fiscal_year] = r.value
        return out


SYMBOL_US_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
