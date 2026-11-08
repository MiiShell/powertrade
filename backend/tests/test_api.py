from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_liveness_and_headers() -> None:
    app = create_app(Settings(env="dev", allowed_origins="https://localhost:8443"))
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        assert r.headers["cache-control"] == "no-store"


def test_csrf_blocked() -> None:
    app = create_app(Settings(env="dev", allowed_origins="https://localhost:8443"))
    with TestClient(app) as client:
        r = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
        assert r.status_code == 403


def test_login_validation() -> None:
    app = create_app(Settings(env="dev"))
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": "a", "password": "b", "totp": "12"})
        assert r.status_code == 422
