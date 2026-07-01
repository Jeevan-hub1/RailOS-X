"""
Infra-backed integration tests — real Kafka / PostgreSQL / Redis round-trips.

These require the docker-compose infrastructure to be running, so they are gated
behind RAILOS_INTEGRATION_INFRA=1. They SKIP cleanly everywhere else (local dev,
the main CI test job) and run for real in the dedicated `integration` CI job
(see .github/workflows/ci.yml), which boots docker-compose first.

Host endpoints (per docker-compose.yml): Kafka localhost:9094,
PostgreSQL localhost:5433, Redis localhost:6380.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

pytestmark = pytest.mark.integration

_INFRA = os.environ.get("RAILOS_INTEGRATION_INFRA") == "1"
requires_infra = pytest.mark.skipif(
    not _INFRA,
    reason="needs docker-compose infra; set RAILOS_INTEGRATION_INFRA=1 to enable",
)

KAFKA = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
DB_URL = os.environ.get("DB_URL", "postgresql://railos:railos-dev@localhost:5433/railos")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6380")


@requires_infra
def test_kafka_produce_consume_roundtrip():
    """Produce a message and read it back through Kafka (auto-created topic)."""
    from kafka import KafkaConsumer, KafkaProducer

    topic = f"integration.test.{uuid.uuid4().hex[:8]}"
    payload = {"eventId": uuid.uuid4().hex, "value": 42}

    producer = KafkaProducer(
        bootstrap_servers=KAFKA,
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    producer.send(topic, payload)
    producer.flush(timeout=15)
    producer.close()

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=KAFKA,
        auto_offset_reset="earliest",
        consumer_timeout_ms=20000,
        value_deserializer=lambda v: json.loads(v.decode()),
    )
    received = [m.value for m in consumer]
    consumer.close()

    assert any(r.get("eventId") == payload["eventId"] for r in received)


@requires_infra
def test_postgres_connectivity():
    """Connect to PostgreSQL and run a trivial query (validates init + creds)."""
    import psycopg2

    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()


@requires_infra
def test_redis_ping():
    """Validate Redis connectivity."""
    redis = pytest.importorskip("redis")

    client = redis.from_url(REDIS_URL)
    assert client.ping() is True
