import json
from datetime import date

from app.market.profile import clean_fmp_profile


def test_clean_profile_happy_path() -> None:
    raw = json.dumps(
        [
            {
                "companyName": "  NVIDIA\nCorporation ",
                "description": "GPUs\t\tand more",
                "sector": "Technology",
                "country": "us",
                "currency": "usd",
                "website": "https://www.nvidia.com",
                "fullTimeEmployees": "36000",
                "ipoDate": "1999-01-22",
                "isin": "US67066G1040",
                "marketCap": 4.5e12,
                "beta": 2.1,
                "lastDividend": 0.04,
                "averageVolume": 2.1e8,
                "isEtf": False,
            }
        ]
    ).encode()
    p = clean_fmp_profile(raw)
    assert p is not None
    assert p.company_name == "NVIDIA Corporation" and p.description == "GPUs and more"
    assert p.country == "US" and p.currency == "USD" and p.employees == 36000
    assert p.ipo_date == date(1999, 1, 22) and p.isin == "US67066G1040" and p.is_etf is False


def test_clean_profile_rejects_bad_values() -> None:
    raw = json.dumps(
        {
            "companyName": "X" * 500,
            "website": "javascript:alert(1)",
            "isin": "NOT-AN-ISIN",
            "country": "USA",
            "fullTimeEmployees": "-5",
            "marketCap": "NaN",
            "ipoDate": "garbage",
            "beta": "inf",
            "isEtf": "yes",
        }
    ).encode()
    p = clean_fmp_profile(raw)
    assert p is not None
    assert len(p.company_name or "") == 200
    assert p.website is None and p.isin is None and p.country is None
    assert p.employees is None and p.market_cap is None and p.ipo_date is None and p.beta is None
    assert p.is_etf is None


def test_clean_profile_errors() -> None:
    assert clean_fmp_profile(b"[]") is None
    assert clean_fmp_profile(b"not json") is None
    assert clean_fmp_profile(json.dumps({"Error Message": "Invalid"}).encode()) is None
