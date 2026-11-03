from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import settings


async def create_redis_pool():
    redis_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))

    return redis_pool
