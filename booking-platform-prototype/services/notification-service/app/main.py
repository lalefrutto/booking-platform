import logging

from fastapi import FastAPI, Query

from .database import notifications_collection
from .kafka_consumer import start_consumer_thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notification-service")

app = FastAPI(title="Notification Service", version="1.0.0")


@app.on_event("startup")
def on_startup():
    start_consumer_thread()
    logger.info("notification-service started, consumer running")


@app.get("/health")
@app.get("/notifications/health")  # алиас: /health снаружи недостижим через префиксный роутинг Traefik
def health():
    return {"status": "ok", "service": "notification-service"}


@app.get("/notifications")
def list_notifications(
    user_id: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
):
    """Журнал уведомлений (для демонстрации; в проде — админ-only).

    user_id необязателен: без него отдаётся общий журнал, с ним — история
    конкретного пользователя.
    """
    query = {"user_id": user_id} if user_id else {}
    cursor = (
        notifications_collection.find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return list(cursor)
