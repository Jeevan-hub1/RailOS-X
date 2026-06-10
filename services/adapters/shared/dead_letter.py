"""
RailOS Dead-Letter Router (Task 3.4)
======================================
Tracks consecutive parse failures per source ID.  When failure_count
reaches the threshold (default 3):
  1. Publishes a ``LEGACY_ADAPTER_FAILURE`` alert to ``monitoring.alerts``
  2. Routes the raw bytes to ``dead-letter.adapter-failures``
  3. Resets the failure counter for that source

Usage::

    router = DeadLetterRouter(producer=kafka_producer, adapter_name="ntes")

    # On a successful parse:
    router.reset(source_id)

    # On a parse failure:
    router.record_failure(source_id, raw_bytes)

Design §4.4 / Req 1 / Task 3.4
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("dead-letter-router")

ALERT_TOPIC = "monitoring.alerts"
DEAD_LETTER_TOPIC = "dead-letter.adapter-failures"
FAILURE_THRESHOLD = 3


class DeadLetterRouter:
    """Tracks consecutive parse failures and routes to dead-letter on threshold."""

    def __init__(
        self,
        producer: Any,
        adapter_name: str,
        adapter_version: str = "1.0.0",
        failure_threshold: int = FAILURE_THRESHOLD,
    ) -> None:
        self._producer = producer
        self._adapter_name = adapter_name
        self._adapter_version = adapter_version
        self._threshold = failure_threshold
        # source_id → consecutive failure count
        self._failures: dict[str, int] = defaultdict(int)

    # ──────────────────────────────────────────────────────────────────────────

    def record_failure(self, source_id: str, raw_payload: bytes) -> bool:
        """
        Record a parse failure for *source_id*.

        Returns True if the threshold was reached and dead-letter routing was
        triggered; False otherwise.
        """
        self._failures[source_id] += 1
        count = self._failures[source_id]
        log.warning(
            "Parse failure %d/%d for source=%s adapter=%s",
            count,
            self._threshold,
            source_id,
            self._adapter_name,
        )

        if count >= self._threshold:
            self._route_to_dead_letter(source_id, raw_payload)
            self._failures[source_id] = 0  # reset counter after routing
            return True
        return False

    def reset(self, source_id: str) -> None:
        """Reset the failure counter for *source_id* on a successful parse."""
        self._failures[source_id] = 0

    def failure_count(self, source_id: str) -> int:
        """Return the current consecutive failure count for *source_id*."""
        return self._failures[source_id]

    # ──────────────────────────────────────────────────────────────────────────

    def _route_to_dead_letter(self, source_id: str, raw_payload: bytes) -> None:
        """Emit LEGACY_ADAPTER_FAILURE alert and route payload to dead-letter."""
        alert = self._build_alert(source_id)
        try:
            self._producer.send(ALERT_TOPIC, value=json.dumps(alert).encode("utf-8"))
            self._producer.flush(timeout=5)
            log.error(
                "LEGACY_ADAPTER_FAILURE emitted: source=%s adapter=%s",
                source_id,
                self._adapter_name,
            )
        except Exception as exc:  # pragma: no cover
            log.error("Failed to publish LEGACY_ADAPTER_FAILURE alert: %s", exc)

        try:
            dead_letter_msg = self._build_dead_letter(source_id, raw_payload)
            self._producer.send(
                DEAD_LETTER_TOPIC,
                value=json.dumps(dead_letter_msg).encode("utf-8"),
            )
            self._producer.flush(timeout=5)
            log.error(
                "Raw payload routed to dead-letter: source=%s len=%d bytes",
                source_id,
                len(raw_payload),
            )
        except Exception as exc:  # pragma: no cover
            log.error("Failed to route payload to dead-letter topic: %s", exc)

    def _build_alert(self, source_id: str) -> dict[str, Any]:
        return {
            "eventId": str(uuid.uuid4()),
            "alertType": "LEGACY_ADAPTER_FAILURE",
            "adapter_name": self._adapter_name,
            "adapter_version": self._adapter_version,
            "sourceId": source_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "consecutive_failures": self._threshold,
            "severity": "ERROR",
        }

    def _build_dead_letter(
        self, source_id: str, raw_payload: bytes
    ) -> dict[str, Any]:
        return {
            "eventId": str(uuid.uuid4()),
            "adapter_name": self._adapter_name,
            "adapter_version": self._adapter_version,
            "sourceId": source_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "raw_payload_hex": raw_payload.hex(),
            "raw_payload_len": len(raw_payload),
        }
