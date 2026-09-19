import os
import json
import logging
import threading
import time
import uuid

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

from .database import session_scope
from . import models
from .kafka_producer import publish_event

logger = logging.getLogger("booking-service.consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPICS = ["payment.completed", "payment.failed"]


def _handle_payment_completed(payload: dict):
    db = session_scope()
    try:
        booking = db.query(models.Booking).filter(models.Booking.id == uuid.UUID(payload["booking_id"])).first()
        if not booking:
            logger.warning("payment.completed for unknown booking %s", payload["booking_id"])
            return
        if booking.status != "PENDING":
            return  # идемпотентность: уже обработано
        booking.status = "CONFIRMED"
        db.commit()
        publish_event(
            "booking.confirmed",
            {
                "booking_id": str(booking.id),
                "user_id": str(booking.user_id),
                "hotel_id": str(booking.hotel_id),
                "room_id": str(booking.room_id),
                "check_in": booking.check_in.isoformat(),
                "check_out": booking.check_out.isoformat(),
            },
        )
    finally:
        db.close()


def _handle_payment_failed(payload: dict):
    db = session_scope()
    try:
        booking = db.query(models.Booking).filter(models.Booking.id == uuid.UUID(payload["booking_id"])).first()
        if not booking:
            logger.warning("payment.failed for unknown booking %s", payload["booking_id"])
            return
        if booking.status != "PENDING":
            return
        booking.status = "CANCELLED"
        booking.cancellation_reason = payload.get("reason", "payment_failed")
        db.commit()
        publish_event(
            "booking.cancelled",
            {
                "booking_id": str(booking.id),
                "user_id": str(booking.user_id),
                "room_id": str(booking.room_id),
                "reason": booking.cancellation_reason,
            },
        )
    finally:
        db.close()


HANDLERS = {
    "payment.completed": _handle_payment_completed,
    "payment.failed": _handle_payment_failed,
}


def _connect_with_retry(max_attempts: int = 30, delay_seconds: int = 3) -> KafkaConsumer:
    for attempt in range(1, max_attempts + 1):
        try:
            return KafkaConsumer(
                *TOPICS,
                bootstrap_servers=KAFKA_BROKER,
                group_id="booking-service",
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
    logger.info("booking-service Kafka consumer listening on %s", TOPICS)
    for message in consumer:
        try:
            handler = HANDLERS.get(message.topic)
            if handler:
                handler(message.value)
        except Exception:
            logger.exception("Failed to process message from %s: %s", message.topic, message.value)


def start_consumer_thread():
    thread = threading.Thread(target=_consume_loop, daemon=True, name="booking-kafka-consumer")
    thread.start()
    return thread
