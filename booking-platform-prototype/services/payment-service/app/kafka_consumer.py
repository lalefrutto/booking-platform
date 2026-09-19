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
from .mock_gateway import charge
from .kafka_producer import publish_event

logger = logging.getLogger("payment-service.consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPICS = ["booking.created"]


def _handle_booking_created(payload: dict):
    db = session_scope()
    try:
        existing = (
            db.query(models.Payment)
            .filter(models.Payment.booking_id == uuid.UUID(payload["booking_id"]))
            .first()
        )
        if existing:
            return  # идемпотентность: платёж уже обработан

        result = charge(payload["amount"])

        if result["success"]:
            payment = models.Payment(
                booking_id=uuid.UUID(payload["booking_id"]),
                user_id=uuid.UUID(payload["user_id"]),
                amount=payload["amount"],
                status="COMPLETED",
                provider_ref=result["provider_ref"],
            )
            db.add(payment)
            db.commit()
            publish_event("payment.completed", {"booking_id": payload["booking_id"], "amount": payload["amount"]})
        else:
            payment = models.Payment(
                booking_id=uuid.UUID(payload["booking_id"]),
                user_id=uuid.UUID(payload["user_id"]),
                amount=payload["amount"],
                status="FAILED",
                failure_reason=result["reason"],
            )
            db.add(payment)
            db.commit()
            publish_event(
                "payment.failed",
                {"booking_id": payload["booking_id"], "reason": result["reason"]},
            )
    finally:
        db.close()


HANDLERS = {"booking.created": _handle_booking_created}


def _connect_with_retry(max_attempts: int = 30, delay_seconds: int = 3) -> KafkaConsumer:
    for attempt in range(1, max_attempts + 1):
        try:
            return KafkaConsumer(
                *TOPICS,
                bootstrap_servers=KAFKA_BROKER,
                group_id="payment-service",
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
    logger.info("payment-service Kafka consumer listening on %s", TOPICS)
    for message in consumer:
        try:
            handler = HANDLERS.get(message.topic)
            if handler:
                handler(message.value)
        except Exception:
            logger.exception("Failed to process message from %s: %s", message.topic, message.value)


def start_consumer_thread():
    thread = threading.Thread(target=_consume_loop, daemon=True, name="payment-kafka-consumer")
    thread.start()
    return thread
