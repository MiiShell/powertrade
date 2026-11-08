"""Password hashing, TOTP, server-side sessions, login throttling, CSRF origin check."""

import hmac
import secrets

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from redis.asyncio import Redis

SESSION_COOKIE = "pt_session"
_ph = PasswordHasher()
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_totp(secret: str, code: str | None) -> bool:
    if not secret:
        return True  # TOTP disabled
    if not code:
        return False
    return bool(pyotp.TOTP(secret).verify(code, valid_window=1))


def check_credentials(
    *, expected_user: str, password_hash: str, totp_secret: str, user: str, password: str, totp: str | None
) -> bool:
    # Always run the expensive hash check to keep timing uniform.
    user_ok = hmac.compare_digest(expected_user.encode(), user.encode())
    pw_ok = verify_password(password_hash, password)
    return user_ok and pw_ok and verify_totp(totp_secret, totp)


class SessionStore:
    """Signed cookie carrying a random session id; session state lives in Redis (revocable)."""

    def __init__(self, redis: Redis, secret: str, max_age: int) -> None:
        self._redis = redis
        self._max_age = max_age
        self._signer = URLSafeTimedSerializer(secret, salt="pt-session")

    async def create(self, user: str) -> str:
        sid = secrets.token_urlsafe(32)
        await self._redis.set(f"pt:session:{sid}", user, ex=self._max_age)
        return self._signer.dumps(sid)

    async def load(self, token: str | None) -> str | None:
        sid = self._sid(token)
        if sid is None:
            return None
        user = await self._redis.get(f"pt:session:{sid}")
        return user.decode() if isinstance(user, bytes) else user

    async def destroy(self, token: str | None) -> None:
        sid = self._sid(token)
        if sid is not None:
            await self._redis.delete(f"pt:session:{sid}")

    def _sid(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            sid = self._signer.loads(token, max_age=self._max_age)
        except BadSignature:
            return None
        return sid if isinstance(sid, str) else None


class LoginThrottle:
    def __init__(self, redis: Redis, max_attempts: int, window_s: int) -> None:
        self._redis = redis
        self._max = max_attempts
        self._window = window_s

    @staticmethod
    def _key(ip: str) -> str:
        return f"pt:login_fail:{ip}"

    async def blocked(self, ip: str) -> bool:
        val = await self._redis.get(self._key(ip))
        return val is not None and int(val) >= self._max

    async def fail(self, ip: str) -> None:
        key = self._key(ip)
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, self._window)

    async def reset(self, ip: str) -> None:
        await self._redis.delete(self._key(ip))


def is_csrf_safe(method: str, origin: str | None, sec_fetch_site: str | None, allowed: set[str]) -> bool:
    """Reject cross-site state-changing requests (defense in depth on top of SameSite=Strict)."""
    if method in {"GET", "HEAD", "OPTIONS"}:
        return True
    if sec_fetch_site == "cross-site":
        return False
    return not (origin is not None and origin.rstrip("/") not in allowed)
