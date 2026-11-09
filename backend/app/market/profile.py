"""Company profile import (FMP /stable/profile) with strict cleaning before it reaches the DB."""

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


@dataclass(frozen=True)
class Profile:
    company_name: str | None = None
    description: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    exchange: str | None = None
    currency: str | None = None
    website: str | None = None
    ceo: str | None = None
    employees: int | None = None
    ipo_date: date | None = None
    isin: str | None = None
    cusip: str | None = None
    market_cap: float | None = None
    beta: float | None = None
    last_dividend: float | None = None
    avg_volume: float | None = None
    is_etf: bool | None = None

    def as_db(self) -> dict[str, Any]:
        return asdict(self)


def _txt(v: Any, max_len: int = 200) -> str | None:
    if not isinstance(v, str):
        return None
    s = " ".join(v.split())  # collapse whitespace/control chars
    return s[:max_len] if s else None


def _num(v: Any, nonneg: bool = False) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float | str):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    if not math.isfinite(f) or (nonneg and f < 0):
        return None
    return f


def clean_fmp_profile(raw: bytes) -> Profile | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict) or "Error Message" in data:
        return None
    website = _txt(data.get("website"))
    if website and not re.match(r"^https?://[^\s]+$", website):
        website = None
    # validate the full value (never truncate into a valid-looking code)
    isin = (_txt(data.get("isin")) or "").upper()
    country = (_txt(data.get("country")) or "").upper()
    currency = (_txt(data.get("currency")) or "").upper()
    ipo: date | None = None
    try:
        ipo = date.fromisoformat(str(data.get("ipoDate"))[:10]) if data.get("ipoDate") else None
    except ValueError:
        ipo = None
    emp = _num(data.get("fullTimeEmployees"), nonneg=True)
    return Profile(
        company_name=_txt(data.get("companyName")),
        description=_txt(data.get("description"), 6000),
        sector=_txt(data.get("sector"), 80),
        industry=_txt(data.get("industry"), 120),
        country=country if re.fullmatch(r"[A-Z]{2}", country) else None,
        exchange=_txt(data.get("exchange"), 40),
        currency=currency if re.fullmatch(r"[A-Z]{3}", currency) else None,
        website=website,
        ceo=_txt(data.get("ceo"), 120),
        employees=int(emp) if emp is not None and emp < 2**31 else None,
        ipo_date=ipo,
        isin=isin if ISIN_RE.fullmatch(isin) else None,
        cusip=_txt(data.get("cusip"), 12),
        market_cap=_num(data.get("marketCap"), nonneg=True),
        beta=_num(data.get("beta")),
        last_dividend=_num(data.get("lastDividend") if "lastDividend" in data else data.get("lastDiv"), True),
        avg_volume=_num(data.get("averageVolume") if "averageVolume" in data else data.get("volAvg"), True),
        is_etf=data.get("isEtf") if isinstance(data.get("isEtf"), bool) else None,
    )
