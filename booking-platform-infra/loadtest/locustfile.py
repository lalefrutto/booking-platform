"""
Нагрузочный сценарий booking-platform (Часть 6).

Ходит через Ingress (Istio Ingress Gateway), повторяя пользовательский путь
из Блока 1: регистрация -> поиск отеля -> проверка доступности -> бронирование
-> иногда отмена. Бронирование запускает сагу через Kafka, поэтому рост
нагрузки виден и как лаг consumer group, и как события автоскейлинга.

Запуск (headless, изнутри кластера):
    locust -f locustfile.py --headless -H http://istio-ingressgateway.istio-system \
           -u 200 -r 10 -t 5m --csv=/results/run
"""
import random
import datetime
import uuid

from locust import HttpUser, task, between, events

# Пул отелей/номеров создаётся один раз на весь прогон: иначе каждый
# виртуальный пользователь плодил бы отели и тест мерил бы запись в каталог,
# а не бронирование.
ROOM_POOL = []
HOTEL_POOL = []


@events.test_start.add_listener
def prepare_catalog(environment, **kwargs):
    """Создаёт отели и номера до начала замеров."""
    import urllib.request
    import json

    base = environment.host.rstrip("/")

    def post(path, payload):
        req = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    for i in range(3):
        hotel = post(
            "/api/hotels",
            {"name": f"LoadTest Hotel {i}", "city": "Moscow", "description": "нагрузочный тест"},
        )
        HOTEL_POOL.append(hotel["id"])
        # Много номеров на отель — чтобы параллельные брони реже конфликтовали
        # по датам и тест мерил пропускную способность, а не борьбу за замок.
        for _ in range(20):
            room = post(
                f"/api/hotels/{hotel['id']}/rooms",
                {"room_type": "Standard", "price_per_night": 3000, "capacity": 2},
            )
            ROOM_POOL.append((hotel["id"], room["id"]))

    print(f"[loadtest] подготовлено отелей: {len(HOTEL_POOL)}, номеров: {len(ROOM_POOL)}")


def random_dates():
    """Случайное окно в пределах года — снижает конкуренцию за одни даты."""
    start = datetime.date(2027, 1, 1) + datetime.timedelta(days=random.randint(0, 330))
    end = start + datetime.timedelta(days=random.randint(1, 4))
    return start.isoformat(), end.isoformat()


class BookingUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        """Регистрация и логин — у каждого виртуального пользователя свой аккаунт."""
        self.user_id = None
        self.token = None
        self.bookings = []

        email = f"load_{uuid.uuid4().hex[:12]}@example.com"
        with self.client.post(
            "/api/users/register",
            json={"email": email, "password": "password123", "full_name": "Load Tester"},
            name="POST /api/users/register",
            catch_response=True,
        ) as r:
            if r.status_code == 201:
                self.user_id = r.json()["id"]
                r.success()
            elif r.status_code == 429:
                # Rate limiter отбил — это ожидаемое поведение, не ошибка теста.
                r.success()
            else:
                r.failure(f"register -> {r.status_code}")
                return

        with self.client.post(
            "/api/users/login",
            json={"email": email, "password": "password123"},
            name="POST /api/users/login",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                self.token = r.json()["access_token"]
                r.success()
            elif r.status_code == 429:
                r.success()
            else:
                r.failure(f"login -> {r.status_code}")

    @task(5)
    def search_hotels(self):
        with self.client.get(
            "/api/hotels?city=Moscow", name="GET /api/hotels?city", catch_response=True
        ) as r:
            if r.status_code in (200, 429):
                r.success()
            else:
                r.failure(f"search -> {r.status_code}")

    @task(5)
    def check_availability(self):
        if not ROOM_POOL:
            return
        _, room_id = random.choice(ROOM_POOL)
        ci, co = random_dates()
        with self.client.get(
            f"/api/rooms/{room_id}/availability?check_in={ci}&check_out={co}",
            name="GET /api/rooms/{id}/availability",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 429):
                r.success()
            else:
                r.failure(f"availability -> {r.status_code}")

    @task(3)
    def create_booking(self):
        """Главная нагрузка: запускает сагу booking.created -> payment -> confirmed."""
        if not ROOM_POOL or not self.user_id:
            return
        hotel_id, room_id = random.choice(ROOM_POOL)
        ci, co = random_dates()
        with self.client.post(
            "/api/bookings",
            json={
                "user_id": self.user_id,
                "hotel_id": hotel_id,
                "room_id": room_id,
                "check_in": ci,
                "check_out": co,
            },
            name="POST /api/bookings",
            catch_response=True,
        ) as r:
            if r.status_code == 202:
                self.bookings.append(r.json()["id"])
                r.success()
            elif r.status_code in (409, 429):
                # 409 — номер занят или его прямо сейчас бронирует другой
                # пользователь (блокировка Valkey). Это корректная бизнес-логика.
                r.success()
            else:
                r.failure(f"booking -> {r.status_code}")

    @task(2)
    def read_booking(self):
        if not self.bookings:
            return
        booking_id = random.choice(self.bookings)
        with self.client.get(
            f"/api/bookings/{booking_id}", name="GET /api/bookings/{id}", catch_response=True
        ) as r:
            if r.status_code in (200, 404, 429):
                r.success()
            else:
                r.failure(f"get booking -> {r.status_code}")

    @task(1)
    def cancel_booking(self):
        """Примерно каждая шестая операция — отмена."""
        if not self.bookings:
            return
        booking_id = self.bookings.pop()
        with self.client.post(
            f"/api/bookings/{booking_id}/cancel",
            name="POST /api/bookings/{id}/cancel",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 409, 404, 429):
                r.success()
            else:
                r.failure(f"cancel -> {r.status_code}")
