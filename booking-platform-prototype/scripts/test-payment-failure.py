#!/usr/bin/env python3
"""
Проверка компенсирующей ветки саги: payment.failed -> booking CANCELLED.

Мок-эквайринг отказывает случайно (PAYMENT_FAILURE_RATE, по умолчанию 10%),
поэтому скрипт сам переводит payment-service в режим гарантированного отказа,
прогоняет сценарий и возвращает исходную настройку.

Запуск:  python scripts/test-payment-failure.py
"""
import json
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.request

BASE = "http://localhost"
PASS, FAIL = [], []


def c(code, text):
    return "\033[" + str(code) + "m" + text + "\033[0m"


def req(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data,
                               headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
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


def recreate_payment(failure_rate):
    print(c(36, "\n-> пересоздаём payment-service с PAYMENT_FAILURE_RATE=" + failure_rate))
    subprocess.run(
        ["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", "payment-service"],
        env={**__import__("os").environ, "PAYMENT_FAILURE_RATE": failure_rate},
        check=True, capture_output=True,
    )
    # ждём, пока контейнер снова станет healthy и consumer подпишется на топик
    for _ in range(30):
        out = subprocess.run(
            ["docker", "compose", "ps", "payment-service", "--format", "{{.Health}}"],
            capture_output=True, text=True).stdout.strip()
        if out == "healthy":
            time.sleep(3)
            return
        time.sleep(2)
    raise RuntimeError("payment-service не стал healthy")


def main():
    recreate_payment("1.0")
    try:
        print(c(36, "\n=== Сценарий: оплата отклонена эквайером ==="))
        st, u = req("POST", BASE + "/api/users/register",
                    {"email": "fail_" + uuid.uuid4().hex[:8] + "@example.com",
                     "password": "password123", "full_name": "Fail Test"})
        if not check("регистрация пользователя", st == 201, st):
            return 1
        uid = u["id"]

        st, h = req("POST", BASE + "/api/hotels",
                    {"name": "Fail Hotel", "city": "Kazan", "description": "для теста отказа"})
        st, room = req("POST", BASE + "/api/hotels/" + h["id"] + "/rooms",
                       {"room_type": "Standard", "price_per_night": 3000, "capacity": 2})
        rid = room["id"]
        ci, co = "2027-03-01", "2027-03-04"

        st, bk = req("POST", BASE + "/api/bookings",
                     {"user_id": uid, "hotel_id": h["id"], "room_id": rid,
                      "check_in": ci, "check_out": co})
        if not check("POST /api/bookings -> 202 PENDING", st == 202 and bk["status"] == "PENDING",
                     "status=" + str(st) + " body=" + str(bk)):
            return 1
        bid = bk["id"]

        final = None
        for _ in range(30):
            st, b = req("GET", BASE + "/api/bookings/" + bid)
            if st == 200 and b["status"] != "PENDING":
                final = b
                break
            time.sleep(1)
        if not check("сага перевела бронь в CANCELLED по payment.failed",
                     final is not None and final["status"] == "CANCELLED", str(final)):
            return 1
        check("указана причина отмены от эквайера",
              final["cancellation_reason"] == "insufficient_funds_or_declined_by_issuer",
              final["cancellation_reason"])

        st, p = req("GET", BASE + "/api/payments/" + bid)
        check("payment-service записал платёж FAILED с failure_reason",
              st == 200 and p["status"] == "FAILED" and p.get("failure_reason"),
              "status=" + str(st) + " body=" + str(p))
        check("у неуспешного платежа нет provider_ref", st == 200 and p.get("provider_ref") is None,
              str(p.get("provider_ref")))

        time.sleep(3)
        st, a = req("GET", BASE + "/api/rooms/" + rid +
                    "/availability?check_in=" + ci + "&check_out=" + co)
        check("номер остался свободен (catalog не блокировал даты)",
              st == 200 and a["available"] is True, str(a))

        notified = False
        for _ in range(15):
            st, notes = req("GET", BASE + "/api/notifications?user_id=" + uid)
            if st == 200 and any(n["event_type"] == "booking.cancelled" and
                                 n["booking_id"] == bid for n in notes):
                notified = True
                break
            time.sleep(1)
        check("notification-service уведомил об отмене", notified, "")

        st, rv = req("POST", BASE + "/api/reviews",
                     {"booking_id": bid, "user_id": uid, "rating": 5, "comment": "x"})
        check("отзыв по неоплаченной броне отклонён (403)", st == 403, "status=" + str(st))
    finally:
        recreate_payment("0.1")

    print(c(36, "\n=== ИТОГ ==="))
    print("  " + c(32, "PASS") + ": " + str(len(PASS)) + "    " + c(31, "FAIL") + ": " + str(len(FAIL)))
    for name, detail in FAIL:
        print("    - " + name + ": " + str(detail))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
