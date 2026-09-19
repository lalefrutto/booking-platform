import os
import json
import logging
import threading
import time
import uuid
import datetime

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

from .database import session_scope
from . import models
from .cache import invalidate_room_cache

logger = logging.getLogger("catalog-service.consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPICS = ["booking.confirmed", "booking.cancelled"]


def _handle_booking_confirmed(payload: dict):
    db = session_scope()
    try:
        exists = (
            db.query(models.BlockedDateRange)
            .filter(models.BlockedDateRange.booking_id == uuid.UUID(payload["booking_id"]))
            .first()
        )
        if exists:
            return  # уже обработано (идемпотентность)
        blocked = models.BlockedDateRange(
            room_id=uuid.UUID(payload["room_id"]),
            booking_id=uuid.UUID(payload["booking_id"]),
            check_in=datetime.date.fromisoformat(payload["check_in"]),
            check_out=datetime.date.fromisoformat(payload["check_out"]),
        )
        db.add(blocked)
        db.commit()
        invalidate_room_cache(payload["room_id"])
        logger.info("Room %s blocked for booking %s", payload["room_id"], payload["booking_id"])
    finally:
        db.close()


def _handle_booking_cancelled(payload: dict):
    db = session_scope()
    try:
        db.query(models.BlockedDateRange).filter(
            models.BlockedDateRange.booking_id == uuid.UUID(payload["booking_id"])
        ).delete()
        db.commit()
        room_id = payload.get("room_id")
        if room_id:
            invalidate_room_cache(room_id)
        logger.info("Booking %s cancelled, room released", payload["booking_id"])
    finally:
        db.close()


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
                group_id="catalog-service",
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
    logger.info("catalog-service Kafka consumer listening on %s", TOPICS)
    for message in consumer:
        try:
            handler = HANDLERS.get(message.topic)
            if handler:
                handler(message.value)
        except Exception:
            logger.exception("Failed to process message from %s: %s", message.topic, message.value)


def start_consumer_thread():
    thread = threading.Thread(target=_consume_loop, daemon=True, name="catalog-kafka-consumer")
    thread.start()
    return thread
