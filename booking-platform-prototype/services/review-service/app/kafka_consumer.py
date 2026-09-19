import os
import json
import logging
import threading
import time

from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

from .database import eligibility_collection

logger = logging.getLogger("review-service.consumer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPICS = ["booking.confirmed"]


def _handle_booking_confirmed(payload: dict):
    """
    Подтверждённая бронь делает пользователя допущенным к отзыву.
    В проде это событие логичнее слушать после даты check_out (например,
    через отложенное сообщение/шедулер), для прототипа упрощаем.
    """
    eligibility_collection.update_one(
        {"booking_id": payload["booking_id"]},
        {
            "$setOnInsert": {
                "booking_id": payload["booking_id"],
                "user_id": payload["user_id"],
                "hotel_id": payload["hotel_id"],
                "reviewed": False,
            }
        },
        upsert=True,
    )
    logger.info("Booking %s is now eligible for a review", payload["booking_id"])


HANDLERS = {"booking.confirmed": _handle_booking_confirmed}


def _connect_with_retry(max_attempts: int = 30, delay_seconds: int = 3) -> KafkaConsumer:
    for attempt in range(1, max_attempts + 1):
        try:
            return KafkaConsumer(
                *TOPICS,
                bootstrap_servers=KAFKA_BROKER,
                group_id="review-service",
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
    logger.info("review-service Kafka consumer listening on %s", TOPICS)
    for message in consumer:
        try:
            handler = HANDLERS.get(message.topic)
            if handler:
                handler(message.value)
        except Exception:
            logger.exception("Failed to process message from %s: %s", message.topic, message.value)


def start_consumer_thread():
    thread = threading.Thread(target=_consume_loop, daemon=True, name="review-kafka-consumer")
    thread.start()
    return thread
