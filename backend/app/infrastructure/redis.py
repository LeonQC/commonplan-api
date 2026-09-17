from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.config import settings


async def create_redis_client() -> Redis:
    # Redis is an optional application-session cache. Constructing the client is
    # deliberately lazy so an outage cannot prevent auth or the API from starting.
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def get_redis_client(request: Request) -> Redis:
    return request.app.state.redis_client


RedisClientDep = Annotated[Redis, Depends(get_redis_client)]
