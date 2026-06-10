"""
RailOS InfluxDB Writer with 3-retry exponential back-off (Task 4.4)
Consumes validated sensor events from Kafka and writes to InfluxDB 3.0.
On write failure: retries 3× (1s/2s/4s), then emits STORAGE_WRITE_FAILURE alert.
NEVER silently discards events.
Satisfies: Req 1 C4 (90-day retention), Req 1 C8 (no silent discard), Design §4.2
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Any

from influxdb_client import InfluxDBClient, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.domain.write_precision import WritePrecision
from kafka import KafkaConsumer, KafkaProducer
from prometheus_client import Counter, Histogram, start_http_server

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)

# ── Configuration ──────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP   = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
INFLUXDB_URL      = os.environ.get("INFLUXDB_URL",   "http://influxdb-primary.railos.svc.cluster.local:8086")
INFLUXDB_TOKEN    = os.environ.get("INFLUXDB_TOKEN",  "railos-admin-token")
INFLUXDB_ORG      = os.environ.get("INFLUXDB_ORG",   "railos")
INFLUXDB_BUCKET   = os.environ.get("INFLUXDB_BUCKET", "sensor-events")
FAILURE_QUEUE_DB  = os.environ.get("FAILURE_QUEUE_DB", "/tmp/write_failures.db")
METRICS_PORT      = int(os.environ.get("METRICS_PORT", "8080"))

SENSOR_TOPICS = [
    "track.sensor.vibration",
    "track.sensor.temperature",
    "track.sensor.acoustic",
    "train.telemetry.position",
    "train.telemetry.omrs",
    "train.telemetry.wild",
]

ALERT_TOPIC      = "monitoring.alerts"
MAX_RETRIES      = 3
BACKOFF_BASE_S   = 1.0

# ── Prometheus metrics ──────────────────────────────────────────────────────────
writes_total         = Counter("influxdb_writes_total",         "Total successful InfluxDB writes")
write_failures_total = Counter("influxdb_write_failures_total", "Total write failures after all retries")
write_latency_ms     = Histogram("influxdb_write_latency_ms",   "InfluxDB write latency in ms",
                                 buckets=[5, 10, 25, 50, 100, 250, 500, 1000])


# ── Failure queue (SQLite) ──────────────────────────────────────────────────────
def _init_failure_queue() -> sqlite3.Connection:
    conn = sqlite3.connect(FAILURE_QUEUE_DB, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS failed_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            topic TEXT,
            payload TEXT,
            failed_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _queue_failure(conn: sqlite3.Connection, event_id: str, topic: str, raw: bytes) -> None:
    conn.execute(
        "INSERT INTO failed_events (event_id, topic, payload) VALUES (?,?,?)",
        (event_id, topic, raw.decode("utf-8", errors="replace")),
    )
    conn.commit()
    log.error("EVENT_QUEUED_TO_FAILURE_STORE event_id=%s topic=%s", event_id, topic)


# ── InfluxDB write helper ───────────────────────────────────────────────────────
def _write_with_retry(write_api: Any, event: dict, topic: str) -> bool:
    """Write one event to InfluxDB. Returns True on success, False on 3 failures."""
    measurement = event.get("sensorType", "unknown")
    asset_id    = event.get("assetId", "unknown")
    payload     = event.get("payload", {})
    ts_utc      = event.get("timestamp_utc", "")

    # Build InfluxDB line-protocol point as a dict for the Python client
    record = {
        "measurement": measurement,
        "tags": {
            "asset_id":   asset_id,
            "source_id":  event.get("sourceId", "unknown"),
            "zone":       event.get("zone", "unknown"),
            "topic":      topic,
        },
        "fields": {k: float(v) if isinstance(v, (int, float)) else str(v)
                   for k, v in payload.items() if v is not None},
        "time": ts_utc,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.monotonic()
        try:
            write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=record)
            write_latency_ms.observe((time.monotonic() - t0) * 1000)
            writes_total.inc()
            return True
        except Exception as exc:
            delay = BACKOFF_BASE_S * (2 ** (attempt - 1))
            log.warning(
                "InfluxDB write attempt %d/%d failed: %s — retrying in %.1fs",
                attempt, MAX_RETRIES, exc, delay,
            )
            if attempt < MAX_RETRIES:
                time.sleep(delay)

    write_failures_total.inc()
    return False


# ── Alert emitter ───────────────────────────────────────────────────────────────
def _emit_write_failure_alert(producer: KafkaProducer, event_id: str, topic: str) -> None:
    alert = {
        "alertType": "STORAGE_WRITE_FAILURE",
        "sourceEventId": event_id,
        "sourceTopic":   topic,
        "message":       "InfluxDB write failed after 3 retries",
    }
    try:
        producer.send(ALERT_TOPIC, value=json.dumps(alert).encode())
        producer.flush(timeout=3)
    except Exception as exc:
        log.error("Failed to emit STORAGE_WRITE_FAILURE alert: %s", exc)


# ── Main loop ───────────────────────────────────────────────────────────────────
def main() -> None:
    start_http_server(METRICS_PORT)
    log.info("InfluxDB writer started (topics=%s)", SENSOR_TOPICS)

    failure_conn = _init_failure_queue()

    influx = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = influx.write_api(write_options=SYNCHRONOUS)

    producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
    consumer = KafkaConsumer(
        *SENSOR_TOPICS,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="influxdb-writer",
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda v: v,
    )

    for msg in consumer:
        raw = msg.value
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("Malformed JSON on topic=%s: %s", msg.topic, exc)
            continue

        event_id = event.get("eventId", "unknown")
        success  = _write_with_retry(write_api, event, msg.topic)

        if not success:
            # Emit alert AND queue to failure store — never silently discard
            _emit_write_failure_alert(producer, event_id, msg.topic)
            _queue_failure(failure_conn, event_id, msg.topic, raw)


if __name__ == "__main__":
    main()
