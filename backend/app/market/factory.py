from redis.asyncio import Redis

from app.market.budget import DailyBudget
from app.settings import Settings


def fmp_budget(redis: Redis, s: Settings) -> DailyBudget:
    return DailyBudget(redis, "fmp", s.fmp_daily_limit, s.fmp_burst, s.fmp_bandwidth_mb_30d * 1024 * 1024)
