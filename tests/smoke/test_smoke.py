"""Smoke tests against a running test deployment (through Caddy, TLS verified against Caddy's internal CA).

Tests run in file order; the rate-limit test must stay last.
"""

import os
import socket
import time
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
    raise SystemExit("SMOKE_ADMIN_PASSWORD is empty – run via scripts/test-deploy.sh")


@pytest.fixture(scope="session")
def ca() -> str:
    deadline = time.time() + 60
    while not Path(CA).exists():
        if time.time() > deadline:
            pytest.fail(f"Caddy root CA not found at {CA}")
        time.sleep(1)
    return CA


@pytest.fixture
def client(ca: str) -> httpx.Client:
    with httpx.Client(base_url=BASE, verify=ca, timeout=20, headers={"Origin": ORIGIN}) as c:
        yield c


def _login(c: httpx.Client, password: str = PASSWORD, with_totp: bool = True) -> httpx.Response:
    body: dict[str, str | None] = {"username": USER, "password": password, "totp": None}
    if TOTP and with_totp:
        body["totp"] = pyotp.TOTP(TOTP).now()
    return c.post("/api/auth/login", json=body)


def test_tls_rejects_untrusted_ca() -> None:
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"{BASE}/api/health", timeout=10)  # system CA store must not trust Caddy's internal CA


def test_liveness(client: httpx.Client) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readiness_all_components(client: httpx.Client) -> None:
    deadline = time.time() + 90
    while True:
        r = client.get("/api/health/ready")
        if r.status_code == 200 or time.time() > deadline:
            break
        time.sleep(2)
    assert r.status_code == 200, r.text
    assert r.json()["checks"] == {"database": "ok", "redis": "ok", "worker": "ok"}


def test_frontend_and_security_headers(client: httpx.Client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "PowerTrade" in r.text
    h = r.headers
    assert "default-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert h["strict-transport-security"].startswith("max-age=")
    assert "server" not in h
    assert "x-powered-by" not in h


def test_api_docs_disabled(client: httpx.Client) -> None:
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def test_protected_endpoints_require_auth(client: httpx.Client) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/system/selfcheck").status_code == 401


def test_wrong_password_rejected(client: httpx.Client) -> None:
    assert _login(client, password="definitely-wrong-password").status_code == 401


def test_totp_required(client: httpx.Client) -> None:
    if not TOTP:
        pytest.skip("TOTP disabled")
    assert _login(client, with_totp=False).status_code == 401


def test_csrf_foreign_origin_blocked(client: httpx.Client) -> None:
    r = client.post("/api/auth/login", json={"username": USER, "password": PASSWORD},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_login_selfcheck_logout(client: httpx.Client) -> None:
    r = _login(client)
    assert r.status_code == 204, r.text
    cookie = r.headers["set-cookie"].lower()
    for attr in ("httponly", "secure", "samesite=strict", "path=/"):
        assert attr in cookie
    token = client.cookies.get("pt_session")
    assert token

    assert client.get("/api/auth/me").json() == {"user": USER}

    r = client.post("/api/system/selfcheck")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["worker"] == data["db_write"] == data["db_read"] == "ok"

    assert client.post("/api/auth/logout").status_code == 204
    # Old token must be revoked server-side, not just dropped by the client.
    replay = client.get("/api/auth/me", cookies={"pt_session": token})
    assert replay.status_code == 401


def test_tampered_cookie_rejected(client: httpx.Client) -> None:
    assert client.get("/api/auth/me", cookies={"pt_session": "forged.token.value"}).status_code == 401


@pytest.mark.parametrize(("host", "port"), [("db", 5432), ("redis", 6379)])
def test_data_services_not_reachable_from_edge(host: str, port: int) -> None:
    with pytest.raises(OSError):
        socket.create_connection((host, port), timeout=3).close()


def test_zz_login_rate_limit(client: httpx.Client) -> None:
    codes = [_login(client, password=f"wrong-{i}").status_code for i in range(7)]
    assert 429 in codes, codes
    # Even the correct password is blocked while throttled.
    assert _login(client).status_code == 429
