import asyncio
from arq import create_pool
from arq.connections import RedisSettings


async def main():
    redis = await create_pool(RedisSettings.from_dsn("redis://localhost:6379/0"))

    job = await redis.enqueue_job(
        "health_check",
        _queue_name="deepresearch",
    )

    print("Job ID:", job.job_id if job else None)

    await redis.aclose()


asyncio.run(main())
