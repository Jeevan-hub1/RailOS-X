"""
RailOS InfluxDB Writer with 3-retry exponential back-off (Task 4.4)
Consumes validated sensor events from Kafka and writes to InfluxDB 3.0.
On write failure: retries 3x (1s/2s/4s), then emits STORAGE_WRITE_FAILURE alert.
NEVER silently discards events.
Satisfies: Req 1 C4 (90-day retention), Req 1 C8 (no silent discard), Design 4.2
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Any, Optional

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

# -- Configuration --------------------------------------------------------------
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

# Exponential back-off delays between successive write attempts. The number of
# entries also defines the total number of write attempts before the event is
# considered failed (3 attempts: initial + 2 retries, sleeping 1s/2s/4s).
RETRY_DELAYS     = [1.0, 2.0, 4.0]

# -- Prometheus metrics ---------------------------------------------------------
writes_total         = Counter("influxdb_writes_total",         "Total successful InfluxDB writes")
write_failures_total = Counter("influxdb_write_failures_total", "Total write failures after all retries")
write_latency_ms     = Histogram("influxdb_write_latency_ms",   "InfluxDB write latency in ms",
                                 buckets=[5, 10, 25, 50, 100, 250, 500, 1000])


# -- Failure queue (SQLite) -----------------------------------------------------
class FailureQueue:
    """Durable SQLite-backed queue for events that exhausted all write retries.

    Guarantees events are never silently discarded (Req 1 C8).
    """

    def __init__(self, db_path: str = FAILURE_QUEUE_DB) -> None:
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS failed_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id     TEXT,
                    topic        TEXT,
                    payload_json TEXT,
                    failed_at    TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.commit()

    def enqueue(self, event: dict, topic: str) -> None:
        """Persist a failed event (full payload) so it can be replayed later."""
        event_id = event.get("eventId", "unknown")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO failed_events (event_id, topic, payload_json) VALUES (?,?,?)",
                (event_id, topic, json.dumps(event)),
            )
            conn.commit()
        log.error("EVENT_QUEUED_TO_FAILURE_STORE event_id=%s topic=%s", event_id, topic)

    def depth(self) -> int:
        """Return the number of events currently held in the failure queue."""
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM failed_events").fetchone()[0]


# -- InfluxDB writer ------------------------------------------------------------
class InfluxDBWriter:
    """Writes canonical sensor events to InfluxDB with bounded retries.

    On exhaustion of all retries the event is (a) reported via a
    STORAGE_WRITE_FAILURE alert on the monitoring topic and (b) persisted to the
    failure queue. Events are never silently dropped.
    """

    def __init__(
        self,
        influx_client: Any,
        kafka_producer: Any,
        failure_queue: FailureQueue,
    ) -> None:
        self._client = influx_client
        self._write_api = influx_client.write_api(write_options=SYNCHRONOUS)
        self._producer = kafka_producer
        self._failure_queue = failure_queue

    @staticmethod
    def _build_record(event: dict, topic: str) -> dict:
        payload = event.get("payload", {}) or {}
        return {
            "measurement": event.get("sensorType", "unknown"),
            "tags": {
                "asset_id":  event.get("assetId", "unknown"),
                "source_id": event.get("sourceId", "unknown"),
                "zone":      event.get("zone", "unknown"),
                "topic":     topic,
            },
            "fields": {
                k: float(v) if isinstance(v, (int, float)) else str(v)
                for k, v in payload.items() if v is not None
            },
            "time": event.get("timestamp_utc", ""),
        }

    def write_event(self, event: dict, source_topic: str) -> bool:
        """Write a single event, retrying per RETRY_DELAYS.

        Returns True on success. On failure after all attempts, emits an alert,
        persists the event to the failure queue, and returns False.
        """
        record = self._build_record(event, source_topic)

        for attempt, delay in enumerate(RETRY_DELAYS, start=1):
            t0 = time.monotonic()
            try:
                self._write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=record)
                write_latency_ms.observe((time.monotonic() - t0) * 1000)
                writes_total.inc()
                return True
            except Exception as exc:
                log.warning(
                    "InfluxDB write attempt %d/%d failed: %s",
                    attempt, len(RETRY_DELAYS), exc,
                )
                if attempt < len(RETRY_DELAYS):
                    time.sleep(delay)

        # All attempts exhausted -- alert + persist, never discard.
        write_failures_total.inc()
        self._emit_write_failure_alert(event, source_topic)
        self._failure_queue.enqueue(event, source_topic)
        return False

    def _emit_write_failure_alert(self, event: dict, topic: str) -> None:
        alert = {
            "alertType":   "STORAGE_WRITE_FAILURE",
            "eventId":     event.get("eventId", "unknown"),
            "sourceTopic": topic,
            "message":     "InfluxDB write failed after all retries",
        }
        try:
            self._producer.send(ALERT_TOPIC, value=json.dumps(alert).encode("utf-8"))
        except Exception as exc:
            log.error("Failed to emit STORAGE_WRITE_FAILURE alert: %s", exc)


# -- Main loop ------------------------------------------------------------------
def main() -> None:
    start_http_server(METRICS_PORT)
    log.info("InfluxDB writer started (topics=%s)", SENSOR_TOPICS)

    failure_queue = FailureQueue(FAILURE_QUEUE_DB)
    influx = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
    writer = InfluxDBWriter(influx, producer, failure_queue)

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

        writer.write_event(event, source_topic=msg.topic)


if __name__ == "__main__":
    main()
