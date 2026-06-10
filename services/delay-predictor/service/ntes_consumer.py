"""
RailOS NTES Consumer with STALE_INPUT detection (Tasks 8.4–8.5)
Satisfies: Req 5 C3, Design §6.3
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP       = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
STALE_THRESHOLD_S     = float(os.environ.get("STALE_THRESHOLD_SECONDS", "60"))
NTES_TOPIC            = "train.telemetry.position"


class NTESConsumer:
    """Background Kafka consumer that maintains a live corridor snapshot."""

    def __init__(self, stale_threshold_s: float = STALE_THRESHOLD_S) -> None:
        self._snapshot: dict[str, dict] = {}
        self._last_update: float = time.monotonic()
        self._lock = threading.Lock()
        self._stale_threshold = stale_threshold_s
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_snapshot(self) -> tuple[dict[str, dict], bool]:
        """Return (snapshot, stale) — stale=True if lag > threshold."""
        with self._lock:
            elapsed = time.monotonic() - self._last_update
            stale = elapsed > self._stale_threshold
            return dict(self._snapshot), stale

    def _update_snapshot(self, msg_value: dict[str, Any]) -> None:
        """Update snapshot from a canonical train.telemetry.position event."""
        payload = msg_value.get("payload", msg_value)
        train_id = msg_value.get("assetId") or payload.get("trainId") or msg_value.get("sourceId", "unknown")
        with self._lock:
            self._snapshot[train_id] = {
                "trainId":             train_id,
                "current_delay_min":   float(payload.get("delay_minutes", 0.0)),
                "load_factor":         float(payload.get("load_factor",   0.5)),
                "schedule_adherence":  float(payload.get("schedule_adherence", 1.0)),
                "stationId":           payload.get("station_code", ""),
                "segmentId":           payload.get("segment_id", ""),
            }
            self._last_update = time.monotonic()

    def _consume_loop(self) -> None:
        try:
            from kafka import KafkaConsumer
            consumer = KafkaConsumer(
                NTES_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id="delay-predictor-ntes",
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda b: json.loads(b.decode()),
            )
            for msg in consumer:
                if not self._running:
                    break
                try:
                    self._update_snapshot(msg.value)
                except Exception as exc:
                    log.warning("NTES message parse error: %s", exc)
        except Exception as exc:
            log.warning("NTESConsumer Kafka unavailable: %s", exc)
