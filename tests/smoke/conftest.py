"""Shared smoke-test config/fixtures. Tests run against Caddy with TLS verified against its internal CA."""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pyotp
import pytest

BASE = os.environ["SMOKE_BASE_URL"]
ORIGIN = os.environ["SMOKE_ORIGIN"]
CA = os.environ["SMOKE_CA"]
USER = os.environ["SMOKE_ADMIN_USER"]
PASSWORD = os.environ["SMOKE_ADMIN_PASSWORD"]
TOTP = os.environ.get("SMOKE_TOTP_SECRET", "")

if not PASSWORD:
    raise SystemExit("SMOKE_ADMIN_PASSWORD is empty - run via scripts/test-deploy.sh")


@pytest.fixture(scope="session")
def ca() -> str:
    deadline = time.time() + 60
    while not Path(CA).exists():
        if time.time() > deadline:
            pytest.fail(f"Caddy root CA not found at {CA}")
        time.sleep(1)
    return CA


@pytest.fixture
def client(ca: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE, verify=ca, timeout=20, headers={"Origin": ORIGIN}) as c:
        yield c


def login(c: httpx.Client, password: str = PASSWORD, with_totp: bool = True) -> httpx.Response:
    body: dict[str, str | None] = {"username": USER, "password": password, "totp": None}
    if TOTP and with_totp:
        body["totp"] = pyotp.TOTP(TOTP).now()
    return c.post("/api/auth/login", json=body)


@pytest.fixture
def authed(client: httpx.Client) -> httpx.Client:
    r = login(client)
    assert r.status_code == 204, r.text
    return client
