from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import ConnectionPool

from app.settings import Settings

WORKER_HEARTBEAT_KEY = "pt:worker:heartbeat"


def redis_settings(s: Settings) -> RedisSettings:
    return RedisSettings(host=s.redis_host, port=s.redis_port, password=s.redis_password or None)


def create_arq_redis(s: Settings) -> ArqRedis:
    """Lazy pool: no network I/O until first command."""
    pool = ConnectionPool(
        host=s.redis_host,
        port=s.redis_port,
        password=s.redis_password or None,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    return ArqRedis(connection_pool=pool)
