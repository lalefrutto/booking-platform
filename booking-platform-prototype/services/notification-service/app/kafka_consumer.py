import os
import json
import logging
import threading
import time
import datetime

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

from .database import notifications_collection
from .sender import send

logger = logging.getLogger("notification-service.consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPICS = ["booking.confirmed", "booking.cancelled"]


def _handle_booking_confirmed(payload: dict):
    message = (
        f"Ваше бронирование {payload['booking_id']} подтверждено! "
        f"Заезд: {payload['check_in']}, выезд: {payload['check_out']}."
    )
    send("email", payload.get("user_id", "unknown"), message)
    notifications_collection.insert_one(
        {
            "booking_id": payload["booking_id"],
            "user_id": payload.get("user_id"),
            "event_type": "booking.confirmed",
            "channel": "email",
            "message": message,
            "created_at": datetime.datetime.utcnow(),
        }
    )


def _handle_booking_cancelled(payload: dict):
    reason = payload.get("reason", "не указана")
    message = f"Бронирование {payload['booking_id']} отменено. Причина: {reason}."
    send("email", payload.get("user_id", "unknown"), message)
    notifications_collection.insert_one(
        {
            "booking_id": payload["booking_id"],
            "user_id": payload.get("user_id"),
            "event_type": "booking.cancelled",
            "channel": "email",
            "message": message,
            "created_at": datetime.datetime.utcnow(),
        }
    )


HANDLERS = {
    "booking.confirmed": _handle_booking_confirmed,
    "booking.cancelled": _handle_booking_cancelled,
}


def _connect_with_retry(max_attempts: int = 30, delay_seconds: int = 3) -> KafkaConsumer:
    for attempt in range(1, max_attempts + 1):
        try:
            return KafkaConsumer(
                *TOPICS,
                bootstrap_servers=KAFKA_BROKER,
                group_id="notification-service",
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
        except NoBrokersAvailable:
            logger.warning("Kafka not ready (attempt %s/%s), retrying...", attempt, max_attempts)
            time.sleep(delay_seconds)
    raise RuntimeError("Could not connect to Kafka after retries")


def _consume_loop():
    consumer = _connect_with_retry()
    logger.info("notification-service Kafka consumer listening on %s", TOPICS)
    for message in consumer:
        try:
            handler = HANDLERS.get(message.topic)
            if handler:
                handler(message.value)
        except Exception:
            logger.exception("Failed to process message from %s: %s", message.topic, message.value)


def start_consumer_thread():
    thread = threading.Thread(target=_consume_loop, daemon=True, name="notification-kafka-consumer")
    thread.start()
    return thread
