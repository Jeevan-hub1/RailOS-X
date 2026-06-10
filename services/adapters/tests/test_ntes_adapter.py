"""
Unit tests for the NTES REST adapter (Task 3.7).

Tests cover:
  1. Valid NTES JSON → correct CanonicalEvent fields
  2. 3 consecutive parse failures → LEGACY_ADAPTER_FAILURE alert emitted
     + dead-letter payload published
  3. Published Kafka message JSON matches canonical schema
"""

from __future__ import annotations

import json
import sys
import os
from typing import Any

import pytest

# Ensure the adapters root is on sys.path so shared/ and ntes/ are importable
_ADAPTERS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ADAPTERS_ROOT not in sys.path:
    sys.path.insert(0, _ADAPTERS_ROOT)

from ntes.ntes_adapter import parse_ntes_record
from shared.canonical_event import CanonicalEvent
from shared.dead_letter import (
    ALERT_TOPIC,
    DEAD_LETTER_TOPIC,
    DeadLetterRouter,
    FAILURE_THRESHOLD,
)
from tests.conftest import MockKafkaProducer


# ── 1. Valid JSON → correct CanonicalEvent ────────────────────────────────────

class TestNtesParseNormalise:
    def test_source_id_derived_from_train_number(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert event.sourceId == "ntes-12345"

    def test_sensor_type_is_gps(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert event.sensorType == "gps"

    def test_asset_id_derived_from_train_number(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert event.assetId == "loco-12345"

    def test_payload_contains_required_fields(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert "latitude" in event.payload
        assert "longitude" in event.payload
        assert "speed_kmh" in event.payload
        assert "station_code" in event.payload

    def test_payload_latitude_value(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert abs(event.payload["latitude"] - 28.6139) < 1e-6

    def test_payload_longitude_value(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert abs(event.payload["longitude"] - 77.2090) < 1e-6

    def test_payload_speed_kmh(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert abs(event.payload["speed_kmh"] - 95.5) < 1e-6

    def test_payload_station_code(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert event.payload["station_code"] == "NDLS"

    def test_sequence_number(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert event.sequence == 42

    def test_schema_version(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        assert event.schema_version == "1.0.0"

    def test_event_id_is_uuid_string(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        import uuid
        uuid.UUID(event.eventId)  # raises if not a valid UUID

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises((KeyError, ValueError)):
            parse_ntes_record({"latitude": 28.6, "longitude": 77.2})  # missing train_number

    def test_bad_latitude_raises(self) -> None:
        bad = {"train_number": "X", "latitude": "not-a-float", "longitude": 77.2}
        with pytest.raises((ValueError, TypeError)):
            parse_ntes_record(bad)


# ── 2. Dead-letter: 3 parse failures → LEGACY_ADAPTER_FAILURE + dead-letter ──

class TestNtesDeadLetterRouting:
    def _make_router(self, producer: MockKafkaProducer) -> DeadLetterRouter:
        return DeadLetterRouter(
            producer=producer,
            adapter_name="ntes",
            adapter_version="1.0.0",
        )

    def test_single_failure_no_dead_letter(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        result = router.record_failure("ntes-X", b"bad-payload")
        assert result is False
        assert len(mock_producer.messages[ALERT_TOPIC]) == 0
        assert len(mock_producer.messages[DEAD_LETTER_TOPIC]) == 0

    def test_two_failures_no_dead_letter(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        router.record_failure("ntes-X", b"bad1")
        result = router.record_failure("ntes-X", b"bad2")
        assert result is False
        assert len(mock_producer.messages[ALERT_TOPIC]) == 0

    def test_three_failures_triggers_dead_letter(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        for _ in range(FAILURE_THRESHOLD - 1):
            router.record_failure("ntes-X", b"bad")
        result = router.record_failure("ntes-X", b"final-bad")
        assert result is True

    def test_three_failures_emits_legacy_adapter_failure_alert(
        self, mock_producer: MockKafkaProducer
    ) -> None:
        router = self._make_router(mock_producer)
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("ntes-Y", b"bad")
        alerts = mock_producer.get_messages(ALERT_TOPIC)
        assert len(alerts) == 1
        assert alerts[0]["alertType"] == "LEGACY_ADAPTER_FAILURE"
        assert alerts[0]["adapter_name"] == "ntes"
        assert alerts[0]["sourceId"] == "ntes-Y"

    def test_three_failures_publishes_to_dead_letter_topic(
        self, mock_producer: MockKafkaProducer
    ) -> None:
        router = self._make_router(mock_producer)
        raw = b"raw-ntes-payload"
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("ntes-Z", raw)
        dead_msgs = mock_producer.get_messages(DEAD_LETTER_TOPIC)
        assert len(dead_msgs) == 1
        assert dead_msgs[0]["adapter_name"] == "ntes"
        # Raw payload is hex-encoded in the dead-letter message
        assert dead_msgs[0]["raw_payload_hex"] == raw.hex()

    def test_counter_resets_after_threshold(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("ntes-R", b"bad")
        # Counter should reset; next failure should not immediately trigger again
        assert router.failure_count("ntes-R") == 0

    def test_reset_on_success_clears_counter(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        router.record_failure("ntes-S", b"bad")
        router.reset("ntes-S")
        assert router.failure_count("ntes-S") == 0


# ── 3. Kafka message JSON matches canonical schema ────────────────────────────

class TestNtesKafkaMessageSchema:
    def test_to_kafka_message_is_valid_json(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        raw = event.to_kafka_message()
        assert isinstance(raw, bytes)
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_kafka_message_has_required_canonical_keys(
        self, ntes_sample_json: dict[str, Any]
    ) -> None:
        event = parse_ntes_record(ntes_sample_json)
        msg = json.loads(event.to_kafka_message())
        required_keys = {
            "eventId", "sourceId", "sensorType", "assetId",
            "timestamp_utc", "sequence", "payload",
            "quality_flags", "schema_version",
        }
        assert required_keys.issubset(msg.keys())

    def test_kafka_message_sensor_type(self, ntes_sample_json: dict[str, Any]) -> None:
        event = parse_ntes_record(ntes_sample_json)
        msg = json.loads(event.to_kafka_message())
        assert msg["sensorType"] == "gps"

    def test_kafka_message_quality_flags_present(
        self, ntes_sample_json: dict[str, Any]
    ) -> None:
        event = parse_ntes_record(ntes_sample_json)
        msg = json.loads(event.to_kafka_message())
        qf = msg["quality_flags"]
        assert "interpolated" in qf
        assert "clock_reliable" in qf
        assert qf["clock_reliable"] is True

    def test_canonical_event_validates_correctly(
        self, ntes_sample_json: dict[str, Any]
    ) -> None:
        """CanonicalEvent Pydantic model does not raise on valid NTES input."""
        event = parse_ntes_record(ntes_sample_json)
        # Re-validate by round-tripping through model_validate
        revalidated = CanonicalEvent.model_validate(event.model_dump())
        assert revalidated.sourceId == event.sourceId
