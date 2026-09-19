#!/usr/bin/env python3
"""
Две проверки слоя устойчивости:

1. Race condition при одновременном бронировании одного номера на одни даты
   (ТЗ п.11) — закрыт короткой блокировкой в Valkey (SET NX PX) плюс проверкой
   пересечения дат в booking_db. Идём напрямую в booking-service (порт 8003),
   чтобы rate limiter гейтвея не смешивался с результатом.

2. Rate limiting на Traefik (ТЗ п.8, NFR «устойчивость к нагрузке»):
   20 rps в среднем, всплеск до 40 — проверяем, что превышение режется 429.

Запуск:  python scripts/test-race-and-ratelimit.py
"""
import collections
import json
import sys
import time
import uuid
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

GATEWAY = "http://localhost"
USER_SVC, CATALOG_SVC, BOOKING_SVC = (
    "http://localhost:8001", "http://localhost:8002", "http://localhost:8003")
PASS, FAIL = [], []


def c(code, text):
    return "\033[" + str(code) + "m" + text + "\033[0m"


def req(method, url, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data,
                               headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except urllib.error.URLError as e:
        return 0, str(e)


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name if cond else (name, detail))
    print("  " + c(32 if cond else 31, "PASS" if cond else "FAIL") + "  " + name +
          ("" if cond else "  -> " + str(detail)))
    return bool(cond)


def test_race():
    print(c(36, "\n=== 1. Race condition: 10 одновременных броней одного номера ==="))
    st, u = req("POST", USER_SVC + "/users/register",
                {"email": "race_" + uuid.uuid4().hex[:8] + "@example.com",
                 "password": "password123", "full_name": "Race Tester"})
    if not check("подготовка: пользователь создан", st == 201, st):
        return
    uid = u["id"]
    st, h = req("POST", CATALOG_SVC + "/hotels",
                {"name": "Race Hotel", "city": "Sochi", "description": "тест гонки"})
    st, room = req("POST", CATALOG_SVC + "/hotels/" + h["id"] + "/rooms",
                   {"room_type": "Suite", "price_per_night": 7000, "capacity": 2})
    payload = {"user_id": uid, "hotel_id": h["id"], "room_id": room["id"],
               "check_in": "2027-05-01", "check_out": "2027-05-05"}

    with ThreadPoolExecutor(max_workers=10) as ex:
        codes = list(ex.map(lambda _: req("POST", BOOKING_SVC + "/bookings", payload)[0],
                            range(10)))
    counter = collections.Counter(codes)
    print("     коды ответов: " + str(dict(counter)))
    check("ровно одна бронь принята (202), остальные отклонены (409)",
          counter.get(202) == 1 and counter.get(409) == 9, dict(counter))

    time.sleep(5)
    st, lst = req("GET", BOOKING_SVC + "/bookings?user_id=" + uid)
    active = [b for b in lst if b["status"] in ("PENDING", "CONFIRMED")]
    check("в booking_db не больше одной активной брони на номер/даты",
          len(active) <= 1, str([b["status"] for b in lst]))


def test_rate_limit():
    print(c(36, "\n=== 2. Rate limiting на Traefik (20 rps, burst 40) ==="))
    url = GATEWAY + "/api/hotels/health"

    def hit(_):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception as e:  # noqa: BLE001
            return str(e)[:40]

    time.sleep(3)  # даём бакету восстановиться
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=50) as ex:
        codes = list(ex.map(hit, range(200)))
    took = time.time() - t0
    counter = collections.Counter(codes)
    print("     200 запросов за %.2fs: %s" % (took, dict(counter)))
    check("часть запросов отбита кодом 429", counter.get(429, 0) > 0, dict(counter))
    check("пропущено примерно burst (40) запросов, а не все 200",
          40 <= counter.get(200, 0) <= 80, "200-х: " + str(counter.get(200, 0)))

    time.sleep(4)
    again = [hit(i) for i in range(5)]
    check("после паузы лимит восстановился", all(x == 200 for x in again), str(again))


def main():
    test_race()
    test_rate_limit()
    print(c(36, "\n=== ИТОГ ==="))
    print("  " + c(32, "PASS") + ": " + str(len(PASS)) + "    " + c(31, "FAIL") + ": " + str(len(FAIL)))
    for name, detail in FAIL:
        print("    - " + name + ": " + str(detail))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
