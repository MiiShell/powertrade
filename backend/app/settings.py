"""Runtime configuration. Secrets are read from `PT_<NAME>_FILE` (Docker secrets) or `PT_<NAME>`."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRET_FIELDS = (
    "db_app_password",
    "db_owner_password",
    "redis_password",
    "session_secret",
    "admin_password_hash",
    "admin_totp_secret",
    "fmp_api_key",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PT_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"

    db_host: str = "db"
    db_port: int = 5432
    db_name: str = "powertrade"
    db_app_user: str = "powertrade_app"
    db_app_password: str = ""
    db_owner_user: str = "powertrade"
    db_owner_password: str = ""

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""

    session_secret: str = ""
    session_max_age: int = 12 * 3600
    cookie_secure: bool = True
    allowed_origins: str = ""  # comma separated, e.g. "https://localhost:8443"

    admin_user: str = "admin"
    admin_password_hash: str = ""
    admin_totp_secret: str = ""

    providers_mode: Literal["live", "fixture"] = "live"
    http_user_agent: str = "Mozilla/5.0 (compatible; PowerTrade/0.1; self-hosted)"

    # Financial Modeling Prep (free plan: 250 calls/day, 500 MB / 30 days). Margins below the hard limits.
    fmp_api_key: str = ""
    fmp_daily_limit: int = 240
    fmp_burst: int = 20
    fmp_bandwidth_mb_30d: int = 450

    login_max_attempts: int = 5
    login_window_s: int = 900

    @model_validator(mode="before")
    @classmethod
    def _load_secret_files(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for name in SECRET_FIELDS:
            path = os.environ.get(f"PT_{name.upper()}_FILE")
            if path and not data.get(name):
                data[name] = Path(path).read_text(encoding="utf-8").strip()
        return data

    @model_validator(mode="after")
    def _require_secrets_outside_dev(self) -> "Settings":
        if self.env == "dev":
            return self
        missing = [
            n
            for n in ("db_app_password", "redis_password", "session_secret", "admin_password_hash")
            if not getattr(self, n)
        ]
        if missing:
            raise ValueError(f"missing required secrets: {', '.join(missing)}")
        if len(self.session_secret) < 32:
            raise ValueError("session_secret must be at least 32 characters")
        return self

    @property
    def origins(self) -> set[str]:
        return {o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()}

    def _db_url(self, driver: str, user: str, password: str) -> str:
        return (
            f"postgresql+{driver}://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def app_db_url(self) -> str:
        return self._db_url("asyncpg", self.db_app_user, self.db_app_password)

    @property
    def owner_db_url(self) -> str:
        return self._db_url("psycopg", self.db_owner_user, self.db_owner_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
