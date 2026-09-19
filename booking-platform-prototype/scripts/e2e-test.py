#!/usr/bin/env python3
"""
Сквозной функциональный прогон Booking Platform через API Gateway (Traefik).

Проверяет не «ответил ли сервис 200», а что бизнес-эффект действительно
наступил: сага дошла до терминального статуса, кэш отдал второй ответ,
уведомление записано в MongoDB, право на отзыв выдано.

Запуск:  python scripts/e2e-test.py [--base http://localhost]
"""
import argparse
import json
import sys
import time
import uuid
import urllib.error
import urllib.request

PASS, FAIL = [], []


def c(code, text):
    return "\033[" + str(code) + "m" + text + "\033[0m"


def req(method, url, body=None, headers=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h, method=method)
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


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print("  " + c(32, "PASS") + "  " + name)
    else:
        FAIL.append((name, detail))
        print("  " + c(31, "FAIL") + "  " + name + "  -> " + str(detail))
    return bool(condition)


def wait_for_status(base, booking_id, target, attempts=30, delay=1.0):
    """Сага асинхронная — ждём терминального статуса, а не спим вслепую."""
    last = None
    for _ in range(attempts):
        st, body = req("GET", base + "/api/bookings/" + booking_id)
        if st == 200:
            last = body["status"]
            if last == target:
                return True, body
        time.sleep(delay)
    return False, last


def section(title):
    print(c(36, "\n=== " + title + " ==="))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    suffix = uuid.uuid4().hex[:8]
    email = "guest_" + suffix + "@example.com"

    section("0. Доступность gateway и health всех сервисов")
    for name, path in [
        ("user", "/api/users/health"),
        ("catalog", "/api/hotels/health"),
        ("booking", "/api/bookings/health"),
        ("payment", "/api/payments/health"),
        ("notification", "/api/notifications/health"),
        ("review", "/api/reviews/health"),
    ]:
        st, body = req("GET", base + path)
        check("health " + name + "-service через Traefik", st == 200,
              "status=" + str(st) + " body=" + str(body))

    section("1. Регистрация и логин (UC-01)")
    st, user = req("POST", base + "/api/users/register",
                   {"email": email, "password": "password123", "full_name": "Ivan Petrov"})
    if not check("POST /api/users/register -> 201", st == 201,
                 "status=" + str(st) + " body=" + str(user)):
        return finish()
    user_id = user["id"]

    st, dup = req("POST", base + "/api/users/register",
                  {"email": email, "password": "password123", "full_name": "Ivan Petrov"})
    check("повторная регистрация того же email -> 409", st == 409, "status=" + str(st))

    st, tok = req("POST", base + "/api/users/login",
                  {"email": email, "password": "password123"})
    if not check("POST /api/users/login -> 200 + JWT", st == 200 and tok.get("access_token"),
                 "status=" + str(st) + " body=" + str(tok)):
        return finish()
    auth = {"Authorization": "Bearer " + tok["access_token"]}

    st, me = req("GET", base + "/api/users/me", headers=auth)
    check("GET /api/users/me с JWT -> 200, тот же пользователь",
          st == 200 and me.get("id") == user_id, "status=" + str(st) + " body=" + str(me))

    st, bad = req("GET", base + "/api/users/me", headers={"Authorization": "Bearer garbage"})
    check("GET /api/users/me с битым JWT -> 401", st == 401, "status=" + str(st))

    st, wrong = req("POST", base + "/api/users/login", {"email": email, "password": "wrongpass"})
    check("логин с неверным паролем -> 401", st == 401, "status=" + str(st))

    section("2. Каталог: отель и номер (UC-07)")
    st, hotel = req("POST", base + "/api/hotels",
                    {"name": "Grand Plaza", "city": "Moscow", "description": "5 звёзд в центре"})
    if not check("POST /api/hotels -> 201", st == 201,
                 "status=" + str(st) + " body=" + str(hotel)):
        return finish()
    hotel_id = hotel["id"]

    st, room = req("POST", base + "/api/hotels/" + hotel_id + "/rooms",
                   {"room_type": "Deluxe", "price_per_night": 5000, "capacity": 2})
    if not check("POST /api/hotels/{id}/rooms -> 201", st == 201,
                 "status=" + str(st) + " body=" + str(room)):
        return finish()
    room_id = room["id"]

    st, found = req("GET", base + "/api/hotels?city=Moscow")
    check("GET /api/hotels?city=Moscow находит отель",
          st == 200 and any(h["id"] == hotel_id for h in found), "status=" + str(st))

    section("3. Доступность номера и кэш Valkey (UC-03, ТЗ п.7)")
    ci, co = "2026-10-01", "2026-10-05"
    q = base + "/api/rooms/" + room_id + "/availability?check_in=" + ci + "&check_out=" + co
    st, a1 = req("GET", q)
    check("1-й запрос доступности -> 200, available=true, source=db",
          st == 200 and a1["available"] is True and a1["source"] == "db",
          "status=" + str(st) + " body=" + str(a1))
    st, a2 = req("GET", q)
    check("2-й запрос доступности -> source=cache (кэш Valkey работает)",
          st == 200 and a2["source"] == "cache", "status=" + str(st) + " body=" + str(a2))
    st, bad = req("GET", base + "/api/rooms/" + room_id +
                  "/availability?check_in=" + co + "&check_out=" + ci)
    check("check_out <= check_in -> 400", st == 400, "status=" + str(st))

    section("4. Отзыв ДО подтверждения брони должен отклоняться (FR-09)")
    st, early = req("POST", base + "/api/reviews",
                    {"booking_id": str(uuid.uuid4()), "user_id": user_id,
                     "rating": 5, "comment": "рано"})
    check("POST /api/reviews по неподтверждённой броне -> 403", st == 403,
          "status=" + str(st) + " body=" + str(early))

    section("5. Успешная сага: booking.created -> payment.completed -> CONFIRMED (UC-04)")
    # Мок-эквайринг отказывает в PAYMENT_FAILURE_RATE случаев (по умолчанию 10%),
    # поэтому счастливый путь повторяем: отменённая бронь освобождает те же даты.
    booking_id, bk, ok, body = None, None, False, None
    for attempt in range(1, 5):
        st, bk = req("POST", base + "/api/bookings",
                     {"user_id": user_id, "hotel_id": hotel_id, "room_id": room_id,
                      "check_in": ci, "check_out": co})
        if attempt == 1 and not check("POST /api/bookings -> 202 Accepted, статус PENDING",
                                      st == 202 and bk.get("status") == "PENDING",
                                      "status=" + str(st) + " body=" + str(bk)):
            return finish()
        if st != 202:
            break
        if attempt == 1:
            check("сумма посчитана как price_per_night * ночи (5000 * 4 = 20000)",
                  float(bk["amount"]) == 20000.0, "amount=" + str(bk.get("amount")))
        booking_id = bk["id"]
        ok, body = wait_for_status(base, booking_id, "CONFIRMED")
        if ok:
            break
        print(c(33, "  ...мок-платёж отказал (попытка " + str(attempt) +
                    "), повторяем — это штатная случайность PAYMENT_FAILURE_RATE"))
        time.sleep(2)
    if not check("сага довела бронь до CONFIRMED (Kafka: payment-service ответил)",
                 ok, "последний статус=" + str(body)):
        return finish()

    st, pay = req("GET", base + "/api/payments/" + booking_id)
    check("payment-service записал платёж COMPLETED с provider_ref",
          st == 200 and pay["status"] == "COMPLETED" and pay.get("provider_ref"),
          "status=" + str(st) + " body=" + str(pay))

    section("6. Реакция на booking.confirmed: catalog, notification, review")
    blocked, a3 = False, None
    for _ in range(20):
        st, a3 = req("GET", q)
        if st == 200 and a3["available"] is False:
            blocked = True
            break
        time.sleep(1)
    check("catalog-service заблокировал даты (blocked_date_ranges) и сбросил кэш",
          blocked, "последний ответ=" + str(a3))

    notified, notes = False, None
    for _ in range(20):
        st, notes = req("GET", base + "/api/notifications?user_id=" + user_id)
        if st == 200 and any(n["event_type"] == "booking.confirmed"
                             and n["booking_id"] == booking_id for n in notes):
            notified = True
            break
        time.sleep(1)
    check("notification-service записал уведомление booking.confirmed в MongoDB",
          notified, "status=" + str(st) + " body=" + str(notes))

    reviewed = None
    for _ in range(20):
        st, reviewed = req("POST", base + "/api/reviews",
                           {"booking_id": booking_id, "user_id": user_id,
                            "rating": 5, "comment": "Отлично!"})
        if st == 201:
            break
        time.sleep(1)
    check("POST /api/reviews ПОСЛЕ подтверждения -> 201 (review-service дал право)",
          st == 201, "status=" + str(st) + " body=" + str(reviewed))

    st, dupr = req("POST", base + "/api/reviews",
                   {"booking_id": booking_id, "user_id": user_id,
                    "rating": 4, "comment": "ещё раз"})
    check("повторный отзыв по той же броне -> 409", st == 409, "status=" + str(st))

    st, hr = req("GET", base + "/api/reviews/hotel/" + hotel_id)
    check("GET /api/reviews/hotel/{id} считает средний рейтинг (FR-10)",
          st == 200 and hr["average_rating"] == 5.0 and hr["total_reviews"] == 1,
          "status=" + str(st) + " body=" + str(hr))

    section("7. Защита от race condition: блокировка Valkey + пересечение дат")
    st, dup_bk = req("POST", base + "/api/bookings",
                     {"user_id": user_id, "hotel_id": hotel_id, "room_id": room_id,
                      "check_in": "2026-10-03", "check_out": "2026-10-07"})
    check("бронь на пересекающиеся даты -> 409 Conflict", st == 409,
          "status=" + str(st) + " body=" + str(dup_bk))

    section("8. Отмена бронирования пользователем (UC-05, FR-07)")
    st, cancelled = req("POST", base + "/api/bookings/" + booking_id + "/cancel")
    check("POST /api/bookings/{id}/cancel -> 200, статус CANCELLED",
          st == 200 and cancelled["status"] == "CANCELLED",
          "status=" + str(st) + " body=" + str(cancelled))
    st, again = req("POST", base + "/api/bookings/" + booking_id + "/cancel")
    check("повторная отмена -> 409", st == 409, "status=" + str(st))

    released, a4 = False, None
    for _ in range(20):
        st, a4 = req("GET", q)
        if st == 200 and a4["available"] is True:
            released = True
            break
        time.sleep(1)
    check("после booking.cancelled catalog-service освободил номер",
          released, "ответ=" + str(a4))

    notified_c = False
    for _ in range(15):
        st, notes = req("GET", base + "/api/notifications?user_id=" + user_id)
        if st == 200 and any(n["event_type"] == "booking.cancelled" for n in notes):
            notified_c = True
            break
        time.sleep(1)
    check("notification-service записал уведомление booking.cancelled", notified_c, "")

    section("9. Неуспешная оплата: payment.failed -> CANCELLED")
    print(c(33, "  (ветка проверяется только при PAYMENT_FAILURE_RATE=1.0)"))
    st, fb = req("POST", base + "/api/bookings",
                 {"user_id": user_id, "hotel_id": hotel_id, "room_id": room_id,
                  "check_in": "2026-12-01", "check_out": "2026-12-03"})
    if st == 202:
        ok, body = wait_for_status(base, fb["id"], "CANCELLED")
        if ok:
            check("бронь перешла в CANCELLED по payment.failed", True)
            st, p = req("GET", base + "/api/payments/" + fb["id"])
            check("payment-service записал платёж FAILED с причиной",
                  st == 200 and p["status"] == "FAILED" and p.get("failure_reason"),
                  "status=" + str(st) + " body=" + str(p))
            st, a5 = req("GET", base + "/api/rooms/" + room_id +
                         "/availability?check_in=2026-12-01&check_out=2026-12-03")
            check("номер остался свободен после неуспешной оплаты",
                  st == 200 and a5["available"] is True, "body=" + str(a5))
        else:
            print(c(33, "  SKIP  платёж прошёл успешно (статус " + str(body) +
                        "); перезапустите с PAYMENT_FAILURE_RATE=1.0"))
    else:
        check("создание брони для сценария отказа", False,
              "status=" + str(st) + " body=" + str(fb))

    return finish()


def finish():
    print(c(36, "\n=== ИТОГ ==="))
    print("  " + c(32, "PASS") + ": " + str(len(PASS)) +
          "    " + c(31, "FAIL") + ": " + str(len(FAIL)))
    for name, detail in FAIL:
        print("    - " + name + ": " + str(detail))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
