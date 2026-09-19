import os
import json
import redis

CACHE_URL = os.getenv("CACHE_URL", "redis://valkey:6379/0")
AVAILABILITY_TTL_SECONDS = int(os.getenv("AVAILABILITY_TTL_SECONDS", "30"))

_client = redis.from_url(CACHE_URL, decode_responses=True)


def availability_key(room_id: str, check_in: str, check_out: str) -> str:
    return f"availability:{room_id}:{check_in}:{check_out}"


def get_cached_availability(key: str):
    raw = _client.get(key)
    return json.loads(raw) if raw else None


def set_cached_availability(key: str, payload: dict, ttl: int = AVAILABILITY_TTL_SECONDS):
    _client.set(key, json.dumps(payload), ex=ttl)


def invalidate_room_cache(room_id: str):
    """Инвалидирует все закэшированные окна доступности для номера.
    Вызывается consumer'ом при получении booking.confirmed / booking.cancelled."""
    pattern = f"availability:{room_id}:*"
    for key in _client.scan_iter(match=pattern):
        _client.delete(key)
