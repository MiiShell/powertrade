"""Alert delivery. Telegram Bot API on a fixed host; the bot token is part of the URL path, so URLs and
exception texts are never logged or stored (only the exception type / API status)."""

import json
import re
from typing import Protocol

import httpx

TELEGRAM_HOST = "https://api.telegram.org"
TOKEN_RE = re.compile(r"^[0-9]{5,15}:[A-Za-z0-9_-]{30,64}$")
CHAT_ID_RE = re.compile(r"^-?[0-9]{1,20}$")
MAX_TEXT = 4000  # Telegram limit 4096
MAX_RESPONSE = 64 * 1024


class NotifyError(Exception):
    """Delivery failed. Message is safe to store (no token / URL)."""


class Notifier(Protocol):
    name: str
    configured: bool

    async def send(self, text: str) -> None: ...


class NullNotifier:
    name = "none"
    configured = False

    def __init__(self, reason: str = "telegram not configured") -> None:
        self.reason = reason

    async def send(self, text: str) -> None:
        raise NotifyError(self.reason)


class FixtureNotifier:
    """Test deployments (no network): records messages in memory."""

    name = "fixture"
    configured = True

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text[:MAX_TEXT])


class TelegramNotifier:
    name = "telegram"
    configured = True

    def __init__(self, client: httpx.AsyncClient, token: str, chat_id: str) -> None:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("invalid telegram bot token format")
        if not CHAT_ID_RE.fullmatch(chat_id):
            raise ValueError("invalid telegram chat id")
        self._client = client
        self._url = f"{TELEGRAM_HOST}/bot{token}/sendMessage"
        self._chat_id = chat_id

    async def send(self, text: str) -> None:
        body = {"chat_id": self._chat_id, "text": text[:MAX_TEXT], "disable_web_page_preview": True}
        try:
            async with self._client.stream("POST", self._url, json=body, timeout=15.0) as r:
                raw = b""
                async for chunk in r.aiter_bytes():
                    raw += chunk
                    if len(raw) > MAX_RESPONSE:
                        raise NotifyError("telegram: response too large")
                status = r.status_code
        except httpx.HTTPError as exc:
            raise NotifyError(f"telegram: {type(exc).__name__}") from None
        if status != 200:
            raise NotifyError(f"telegram: HTTP {status}{_description(raw)}")
        try:
            ok = json.loads(raw).get("ok") is True
        except (ValueError, AttributeError):
            ok = False
        if not ok:
            raise NotifyError("telegram: unexpected response")


def _description(raw: bytes) -> str:
    """Telegram error description (e.g. 'chat not found'), sanitised and truncated."""
    try:
        desc = str(json.loads(raw).get("description", ""))
    except (ValueError, AttributeError):
        return ""
    desc = re.sub(r"[^\w .:,'-]", "", desc)[:120]
    return f" ({desc})" if desc else ""


def build_notifier(mode: str, client: httpx.AsyncClient | None, token: str, chat_id: str) -> Notifier:
    if mode == "fixture":
        return FixtureNotifier()
    if client is None or not token or not chat_id:
        return NullNotifier()
    try:
        return TelegramNotifier(client, token, chat_id)
    except ValueError as exc:  # message never contains the token
        return NullNotifier(f"telegram misconfigured: {exc}")
