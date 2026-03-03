import time

import redis.asyncio as redis

_client: redis.Redis | None = None
_key: str = "graphrag:query_active"
_ttl: int = 120


def init_tracker(redis_client: redis.Redis, key: str, ttl: int):
    global _client, _key, _ttl
    _client = redis_client
    _key = key
    _ttl = ttl


async def mark_active():
    await _client.set(_key, str(int(time.time())), ex=_ttl)


async def get_activity() -> dict:
    val = await _client.get(_key)
    if val is None:
        return {"active": False, "last_query_at": None, "ttl_remaining": 0}

    ttl_remaining = await _client.ttl(_key)
    return {
        "active": True,
        "last_query_at": val,
        "ttl_remaining": max(ttl_remaining, 0),
    }
