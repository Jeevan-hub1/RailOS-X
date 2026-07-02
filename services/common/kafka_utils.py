"""
RailOS Shared Kafka Utilities
===============================
Centralises Kafka producer creation and one-shot alert publishing, eliminating
identical boilerplate across adapters, model governance, and other services.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092",
)

MONITORING_ALERTS_TOPIC = "monitoring.alerts"

# Graceful fallback for environments without kafka-python (unit tests)
try:
    from kafka import KafkaProducer
    from kafka.errors import KafkaError
except ImportError:  # pragma: no cover
    KafkaProducer = None  # type: ignore[assignment,misc]
    KafkaError = Exception  # type: ignore[assignment,misc]


def make_kafka_producer(
    bootstrap_servers: str | None = None,
    **overrides: Any,
) -> Any:
    """Create a KafkaProducer with standard RailOS defaults.

    Raises ``RuntimeError`` if kafka-python is not installed.
    """
    if KafkaProducer is None:
        raise RuntimeError("kafka-python is not installed")
    defaults: dict[str, Any] = {
        "bootstrap_servers": bootstrap_servers or KAFKA_BOOTSTRAP,
        "acks": "all",
        "retries": 3,
        "retry_backoff_ms": 500,
    }
    defaults.update(overrides)
    return KafkaProducer(**defaults)


def publish_alert(payload: dict[str, Any], topic: str = MONITORING_ALERTS_TOPIC) -> None:
    """Publish a JSON alert to a Kafka topic using a short-lived producer.

    Used by model-governance modules and other services that emit infrequent
    one-shot alerts (e.g. ``REGRESSION_DETECTED``, ``MODEL_DRIFT_ALERT``,
    ``BIAS_THRESHOLD_EXCEEDED``).

    Non-fatal: logs a warning on failure but never raises.
    """
    try:
        producer = make_kafka_producer()
        producer.send(topic, value=json.dumps(payload).encode("utf-8"))
        producer.flush(timeout=5)
        producer.close(timeout=5)
    except Exception as exc:
        log.warning("Kafka alert publish to %s failed: %s", topic, exc)
