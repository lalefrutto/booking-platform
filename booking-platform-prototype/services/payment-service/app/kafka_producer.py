import os
import json
import logging

from kafka import KafkaProducer

logger = logging.getLogger("payment-service.producer")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")

_producer: KafkaProducer | None = None


def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=5,
            linger_ms=20,
        )
    return _producer


def publish_event(topic: str, payload: dict):
    producer = get_producer()
    future = producer.send(topic, value=payload)
    try:
        future.get(timeout=10)
        logger.info("Published event to %s: %s", topic, payload)
    except Exception:
        logger.exception("Failed to publish event to %s", topic)
        raise
