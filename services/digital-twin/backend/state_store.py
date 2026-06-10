"""
RailOS Digital Twin State Store (Tasks 13.2–13.3)
Kafka consumer → InfluxDB state store + topology conflict detector.
Satisfies: Req 8, Req 21, Design §7.1 Layer C
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP   = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                    "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
INFLUXDB_URL      = os.environ.get("INFLUXDB_URL",   "http://influxdb-primary.railos.svc.cluster.local:8086")
INFLUXDB_TOKEN    = os.environ.get("INFLUXDB_TOKEN",  "railos-admin-token")
INFLUXDB_ORG      = os.environ.get("INFLUXDB_ORG",   "railos")
INFLUXDB_BUCKET   = os.environ.get("INFLUXDB_BUCKET_DT", "digital-twin-state")

SUBSCRIBED_TOPICS = [
    "train.telemetry.position",
    "maintenance.advisories",
    "vision.defect.alerts",
    "security.anomalies",
    "scheduling.proposals",
    "monitoring.alerts",
]


class ConflictDetector:
    """Detects topology-violating train position updates (Task 13.3, Req 21 C2)."""

    def __init__(self, track_segments: dict[str, dict]) -> None:
        # segment_id → {max_concurrent_trains, current_occupants: set}
        self._segments = track_segments
        self._segment_occupants: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def validate_update(self, train_id: str, segment_id: str) -> tuple[bool, Optional[str]]:
        """Return (valid, reason). Rejects if segment at capacity."""
        if not segment_id:
            return True, None  # no segment info — accept

        max_cap = self._segments.get(segment_id, {}).get("max_concurrent_trains", 1)
        with self._lock:
            occupants = self._segment_occupants.get(segment_id, set())
            if len(occupants) >= max_cap and train_id not in occupants:
                reason = (
                    f"Segment {segment_id} at capacity "
                    f"({len(occupants)}/{max_cap}): {sorted(occupants)}"
                )
                log.warning("CONFLICT_DETECTED %s", reason)
                return False, reason
            # Accept and track
            self._segment_occupants.setdefault(segment_id, set()).add(train_id)
            return True, None

    def clear_train(self, train_id: str) -> None:
        """Remove a train from all segment occupancy records."""
        with self._lock:
            for seg_set in self._segment_occupants.values():
                seg_set.discard(train_id)


class DigitalTwinStateStore:
    """Consumes all advisory/telemetry topics; writes state to InfluxDB."""

    def __init__(self, conflict_detector: Optional[ConflictDetector] = None) -> None:
        self._state: dict[str, Any] = {}
        self._conflict_detector = conflict_detector
        self._lock = threading.Lock()
        self._inconsistency_log: list[dict] = []

    # ── Public API ──────────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def process_event(self, topic: str, event: dict) -> bool:
        """Process a Kafka event. Returns False if rejected by conflict detector."""
        if topic == "train.telemetry.position":
            return self._update_train_position(event)
        elif topic == "maintenance.advisories":
            self._update_advisory(event, "maintenance")
        elif topic == "vision.defect.alerts":
            self._update_advisory(event, "defect")
        elif topic == "security.anomalies":
            self._update_advisory(event, "security")
        elif topic == "scheduling.proposals":
            self._update_proposal(event)
        return True

    def _update_train_position(self, event: dict) -> bool:
        payload   = event.get("payload", event)
        train_id  = event.get("assetId", payload.get("trainId", "unknown"))
        segment   = payload.get("segment_id", "")

        if self._conflict_detector and segment:
            valid, reason = self._conflict_detector.validate_update(train_id, segment)
            if not valid:
                self._inconsistency_log.append({
                    "eventId":     event.get("eventId", ""),
                    "reason":      reason,
                    "timestamp":   datetime.now(timezone.utc).isoformat(),
                })
                return False

        with self._lock:
            self._state.setdefault("trains", {})[train_id] = {
                "trainId":        train_id,
                "lat":            payload.get("latitude",  0.0),
                "lon":            payload.get("longitude", 0.0),
                "speed_kmh":      payload.get("speed_kmh", 0.0),
                "delay_min":      payload.get("delay_minutes", 0.0),
                "segment_id":     segment,
                "updated_at":     event.get("timestamp_utc", ""),
            }
        return True

    def _update_advisory(self, event: dict, category: str) -> None:
        alert_id = event.get("alertId", event.get("proposalId", str(id(event))))
        with self._lock:
            self._state.setdefault("advisories", {})[alert_id] = {
                "category":    category,
                "event":       event,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }

    def _update_proposal(self, event: dict) -> None:
        pid = event.get("proposalId", str(id(event)))
        with self._lock:
            self._state.setdefault("proposals", {})[pid] = event

    # ── Consumer loop ────────────────────────────────────────────────────────────

    def run_consumer_loop(self) -> None:
        try:
            from kafka import KafkaConsumer
        except ImportError:
            log.error("kafka-python not installed")
            return

        consumer = KafkaConsumer(
            *SUBSCRIBED_TOPICS,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id="digital-twin-state-store",
            auto_offset_reset="latest",
            value_deserializer=lambda b: json.loads(b.decode()),
        )
        log.info("Digital Twin state store consumer started")
        for msg in consumer:
            try:
                self.process_event(msg.topic, msg.value)
            except Exception as exc:
                log.error("State store error: %s", exc)
