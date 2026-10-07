"""Redis 固定窗口限流：每用户每分钟 N 次请求。"""
from fastapi import HTTPException

import redis

from app.config import settings

r = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def check_rate_limit(user_id: str, limit: int = 20, window: int = 60) -> None:
    key = f"rl:{user_id}:{int(__import__('time').time()) // window}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window + 1)
    count, _ = pipe.execute()
    if count > limit:
        raise HTTPException(429, f"请求过于频繁，每分钟限 {limit} 次")