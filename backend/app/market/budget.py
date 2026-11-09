"""Shared API budget (Redis): daily call cap paced over the day + rolling 30-day bandwidth cap.

Pacing: by time t (UTC) at most `burst + limit * t/24h` calls may have been made, so the daily
quota is spread across the day instead of being burnt at once.
"""

from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

_ACQUIRE = """
if redis.call('EXISTS', KEYS[2]) == 1 then return -2 end
local n = tonumber(redis.call('GET', KEYS[1]) or '0')
if n >= tonumber(ARGV[1]) then return -1 end
n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
return n
"""


class BudgetExceeded(Exception):
    pass


class DailyBudget:
    def __init__(
        self, redis: Redis, name: str, daily_limit: int, burst: int, bandwidth_bytes_30d: int
    ) -> None:
        self._r = redis
        self._name = name
        self.daily_limit = daily_limit
        self.burst = burst
        self.bandwidth_limit = bandwidth_bytes_30d

    def _k(self, kind: str, day: str) -> str:
        return f"pt:budget:{self._name}:{kind}:{day}"

    def cap_now(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        secs = now.hour * 3600 + now.minute * 60 + now.second
        return min(self.daily_limit, self.burst + int(self.daily_limit * secs / 86400))

    async def bytes_30d(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        keys = [self._k("bytes", (now - timedelta(days=i)).strftime("%Y%m%d")) for i in range(30)]
        vals = await self._r.mget(keys)
        return sum(int(v) for v in vals if v is not None)

    async def acquire(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        if await self.bytes_30d(now) >= self.bandwidth_limit:
            raise BudgetExceeded("bandwidth cap (30 days) reached")
        day = now.strftime("%Y%m%d")
        res = int(
            await self._r.eval(  # type: ignore[misc]
                _ACQUIRE,
                2,
                self._k("calls", day),
                self._k("blocked", day),
                str(self.cap_now(now)),
                str(2 * 86400),
            )
        )
        if res == -2:
            raise BudgetExceeded("provider blocked for today (rate limited)")
        if res == -1:
            raise BudgetExceeded("daily budget paced: try again later")
        return res

    async def record_bytes(self, n: int, now: datetime | None = None) -> None:
        key = self._k("bytes", (now or datetime.now(UTC)).strftime("%Y%m%d"))
        await self._r.incrby(key, n)
        await self._r.expire(key, 31 * 86400)

    async def block_today(self, now: datetime | None = None) -> None:
        await self._r.set(self._k("blocked", (now or datetime.now(UTC)).strftime("%Y%m%d")), "1", ex=86400)

    async def usage(self, now: datetime | None = None) -> dict[str, int | bool]:
        now = now or datetime.now(UTC)
        day = now.strftime("%Y%m%d")
        calls = await self._r.get(self._k("calls", day))
        return {
            "calls_today": int(calls) if calls else 0,
            "allowed_now": self.cap_now(now),
            "daily_limit": self.daily_limit,
            "bytes_30d": await self.bytes_30d(now),
            "bandwidth_limit_30d": self.bandwidth_limit,
            "blocked_today": bool(await self._r.exists(self._k("blocked", day))),
        }
