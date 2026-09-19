"""
Короткоживущая распределённая блокировка на Valkey (SET NX PX).

Закрывает race condition, описанный в п. 11 ТЗ: между синхронной проверкой
доступности в Catalog Service и коммитом брони в booking_db есть окно, в котором
второй гость успевает получить тот же ответ "available: true" на те же даты.

Блокировка берётся на (room_id, check_in, check_out) до проверки доступности и
снимается после того, как бронь закоммичена и событие booking.created
опубликовано, т.е. после того, как сага уже началась. Дальше конкурента
останавливает blocked_date_ranges в Catalog Service.

Снятие блокировки — Lua-скриптом со сверкой токена владельца, чтобы процесс,
у которого блокировка уже протухла по TTL, не снял чужую.
"""
import os
import uuid
import logging
import contextlib

import redis

logger = logging.getLogger("booking-service.locks")

LOCK_URL = os.getenv("LOCK_URL", os.getenv("CACHE_URL", "redis://valkey:6379/1"))
LOCK_TTL_MS = int(os.getenv("BOOKING_LOCK_TTL_MS", "10000"))

_client = redis.from_url(LOCK_URL, decode_responses=True)

# Снимаем блокировку, только если она всё ещё наша.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""
_release = _client.register_script(_RELEASE_LUA)


class RoomLockBusy(Exception):
    """Номер на эти даты прямо сейчас бронирует кто-то другой."""


def lock_key(room_id: str, check_in: str, check_out: str) -> str:
    return f"lock:booking:{room_id}:{check_in}:{check_out}"


@contextlib.contextmanager
def room_lock(room_id: str, check_in: str, check_out: str):
    key = lock_key(room_id, check_in, check_out)
    token = uuid.uuid4().hex
    acquired = _client.set(key, token, nx=True, px=LOCK_TTL_MS)
    if not acquired:
        logger.warning("Lock busy for %s", key)
        raise RoomLockBusy(key)
    logger.info("Acquired lock %s", key)
    try:
        yield
    finally:
        try:
            _release(keys=[key], args=[token])
            logger.info("Released lock %s", key)
        except redis.RedisError:
            # TTL всё равно снимет блокировку — не роняем запрос из-за этого.
            logger.exception("Failed to release lock %s", key)
