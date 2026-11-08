import pyotp
import pytest

from app.security import check_credentials, hash_password, is_csrf_safe, verify_password, verify_totp
from app.settings import Settings


def test_password_roundtrip() -> None:
    h = hash_password("correct horse battery")
    assert verify_password(h, "correct horse battery")
    assert not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "x")
    assert not verify_password("", "x")


def test_totp() -> None:
    secret = pyotp.random_base32()
    assert verify_totp("", None)  # disabled
    assert not verify_totp(secret, None)
    assert verify_totp(secret, pyotp.TOTP(secret).now())
    assert not verify_totp(secret, "000000") or pyotp.TOTP(secret).now() == "000000"


def test_check_credentials() -> None:
    h = hash_password("s3cret-password")
    kw = {"expected_user": "admin", "password_hash": h, "totp_secret": ""}
    assert check_credentials(**kw, user="admin", password="s3cret-password", totp=None)
    assert not check_credentials(**kw, user="root", password="s3cret-password", totp=None)
    assert not check_credentials(**kw, user="admin", password="nope", totp=None)


@pytest.mark.parametrize(
    ("method", "origin", "sfs", "expected"),
    [
        ("GET", "https://evil.example", "cross-site", True),
        ("POST", None, None, True),
        ("POST", "https://localhost:8443", "same-origin", True),
        ("POST", "https://evil.example", None, False),
        ("POST", None, "cross-site", False),
        ("DELETE", "https://localhost:8443/", None, True),
    ],
)
def test_csrf(method: str, origin: str | None, sfs: str | None, expected: bool) -> None:
    assert is_csrf_safe(method, origin, sfs, {"https://localhost:8443"}) is expected


def test_settings_require_secrets_outside_dev() -> None:
    with pytest.raises(ValueError, match="missing required secrets"):
        Settings(env="prod")
    with pytest.raises(ValueError, match="at least 32"):
        Settings(
            env="prod",
            db_app_password="x",
            redis_password="x",
            session_secret="short",
            admin_password_hash="x",
        )


def test_settings_secret_files(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "pw"
    f.write_text("p@ss/word\n")
    monkeypatch.setenv("PT_DB_APP_PASSWORD_FILE", str(f))
    s = Settings()
    assert s.db_app_password == "p@ss/word"
    assert "p%40ss%2Fword" in s.app_db_url
