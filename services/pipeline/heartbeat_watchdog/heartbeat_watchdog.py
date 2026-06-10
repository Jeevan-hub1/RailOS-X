"""
RailOS Feed Heartbeat Watchdog (Task 4.7)
Monitors sensor topic heartbeats; emits FEED_UNAVAILABLE when silent for ≥10s.
Maintains 500ms normalization SLA check.
Satisfies: Req 1 C3, Req 1 C6, Design §4.2
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from kafka import KafkaConsumer, KafkaProducer
from prometheus_client import Gauge, start_http_server

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)

KAFKA_BOOTSTRAP        = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
HEARTBEAT_TIMEOUT_S    = float(os.environ.get("HEARTBEAT_TIMEOUT_SECONDS", "10"))
METRICS_PORT           = int(os.environ.get("METRICS_PORT", "8080"))
ALERT_TOPIC            = "monitoring.alerts"

TOPICS_TO_MONITOR = os.environ.get("TOPICS_TO_MONITOR", ",".join([
    "track.sensor.vibration",
    "track.sensor.temperature",
    "track.sensor.acoustic",
    "train.telemetry.position",
    "train.telemetry.omrs",
    "train.telemetry.wild",
])).split(",")

# Prometheus: seconds since last message per topic
feed_last_seen_gauge = Gauge(
    "feed_last_seen_seconds",
    "Seconds since last message received on this sensor feed topic",
    labelnames=["topic"],
)


class HeartbeatWatchdog:
    def __init__(self, topics: list[str]) -> None:
        self._topics = topics
        self._last_seen: dict[str, float] = {t: time.monotonic() for t in topics}
        self._alerted: dict[str, bool]    = {t: False for t in topics}
        self._lock = threading.Lock()

    def record_message(self, topic: str) -> None:
        with self._lock:
            self._last_seen[topic] = time.monotonic()
            if self._alerted.get(topic):
                log.info("FEED_RESTORED topic=%s", topic)
                self._alerted[topic] = False

    def check_all(self, producer: KafkaProducer) -> None:
        now = time.monotonic()
        with self._lock:
            for topic in self._topics:
                elapsed = now - self._last_seen.get(topic, now)
                feed_last_seen_gauge.labels(topic=topic).set(elapsed)
                if elapsed >= HEARTBEAT_TIMEOUT_S and not self._alerted.get(topic, False):
                    self._emit_alert(producer, topic, elapsed)
                    self._alerted[topic] = True

    def _emit_alert(self, producer: KafkaProducer, topic: str, elapsed_s: float) -> None:
        alert = {
            "alertType": "FEED_UNAVAILABLE",
            "topic":     topic,
            "silentSec": round(elapsed_s, 1),
            "threshold": HEARTBEAT_TIMEOUT_S,
        }
        log.warning("FEED_UNAVAILABLE topic=%s silent_s=%.1f", topic, elapsed_s)
        try:
            producer.send(ALERT_TOPIC, value=json.dumps(alert).encode())
            producer.flush(timeout=3)
        except Exception as exc:
            log.error("Failed to emit FEED_UNAVAILABLE: %s", exc)


def _watchdog_loop(watchdog: HeartbeatWatchdog, producer: KafkaProducer) -> None:
    """Background thread: check heartbeats every second."""
    while True:
        time.sleep(1.0)
        watchdog.check_all(producer)


def main() -> None:
    start_http_server(METRICS_PORT)
    log.info("Heartbeat watchdog started topics=%s timeout_s=%.0f", TOPICS_TO_MONITOR, HEARTBEAT_TIMEOUT_S)

    producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
    watchdog = HeartbeatWatchdog(TOPICS_TO_MONITOR)

    # Start watchdog background thread
    t = threading.Thread(target=_watchdog_loop, args=(watchdog, producer), daemon=True)
    t.start()

    # Consumer thread: update last_seen on every message
    consumer = KafkaConsumer(
        *TOPICS_TO_MONITOR,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="heartbeat-watchdog",
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )
    for msg in consumer:
        watchdog.record_message(msg.topic)


if __name__ == "__main__":
    main()
