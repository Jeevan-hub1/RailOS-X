"""
Unit tests for the WILD stream adapter (Task 3.7).

Tests cover:
  1. Valid 64-byte WILD record decode → correct CanonicalEvent fields
  2. axle_loads length equals axle_count
  3. 3 consecutive parse failures → dead-letter routing triggered
"""

from __future__ import annotations

import json
import os
import struct
import sys
from typing import Any

import pytest

_ADAPTERS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ADAPTERS_ROOT not in sys.path:
    sys.path.insert(0, _ADAPTERS_ROOT)

from wild.wild_adapter import parse_wild_record, WILD_RECORD_SIZE
from shared.canonical_event import CanonicalEvent
from shared.dead_letter import (
    ALERT_TOPIC,
    DEAD_LETTER_TOPIC,
    DeadLetterRouter,
    FAILURE_THRESHOLD,
)
from tests.conftest import MockKafkaProducer, build_wild_record


# ── 1. Valid 64-byte record decode ────────────────────────────────────────────

class TestWildRecordDecode:
    def test_sensor_type_is_wheel_load(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        assert event.sensorType == "wheel_load"

    def test_source_id_contains_train_id(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        assert "TR56789" in event.sourceId

    def test_asset_id_contains_train_id(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        assert "TR56789" in event.assetId

    def test_payload_has_train_id(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        assert event.payload["train_id"] == "TR56789"

    def test_payload_has_axle_loads(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        assert "axle_loads" in event.payload
        assert isinstance(event.payload["axle_loads"], list)

    def test_payload_has_max_load(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        assert "max_load" in event.payload
        assert event.payload["max_load"] == max(event.payload["axle_loads"])

    def test_payload_has_timestamp_utc(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        assert "timestamp_utc" in event.payload
        assert isinstance(event.payload["timestamp_utc"], str)
        # Should be ISO-8601 format
        assert "T" in event.payload["timestamp_utc"]

    def test_schema_version(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        assert event.schema_version == "1.0.0"

    def test_event_id_is_uuid(self, wild_binary_record: bytes) -> None:
        import uuid
        event = parse_wild_record(wild_binary_record)
        uuid.UUID(event.eventId)

    def test_canonical_event_validates(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        revalidated = CanonicalEvent.model_validate(event.model_dump())
        assert revalidated.sensorType == "wheel_load"

    def test_kafka_message_is_valid_json(self, wild_binary_record: bytes) -> None:
        event = parse_wild_record(wild_binary_record)
        msg = json.loads(event.to_kafka_message())
        assert msg["sensorType"] == "wheel_load"
        assert "axle_loads" in msg["payload"]

    def test_wrong_size_raises(self) -> None:
        with pytest.raises((ValueError, struct.error)):
            parse_wild_record(b"\x00" * 32)  # too short

    def test_zero_length_raises(self) -> None:
        with pytest.raises((ValueError, struct.error)):
            parse_wild_record(b"")

    def test_axle_count_zero_raises(self) -> None:
        rec = build_wild_record(axle_count=0)
        with pytest.raises(ValueError, match="axle_count"):
            parse_wild_record(rec)

    def test_axle_count_nine_raises(self) -> None:
        # axle_count > 8 is invalid
        rec = build_wild_record(axle_count=9)
        with pytest.raises(ValueError, match="axle_count"):
            parse_wild_record(rec)

    def test_record_is_exactly_64_bytes(self, wild_binary_record: bytes) -> None:
        assert len(wild_binary_record) == 64
        assert WILD_RECORD_SIZE == 64


# ── 2. axle_loads length == axle_count ───────────────────────────────────────

class TestWildAxleLoadsLength:
    @pytest.mark.parametrize("axle_count", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_axle_loads_length_equals_axle_count(self, axle_count: int) -> None:
        """
        Core correctness property: the normalised axle_loads list must contain
        exactly axle_count elements — no more, no fewer.
        """
        loads = [float(10 + i) for i in range(axle_count)] + [0.0] * (8 - axle_count)
        record = build_wild_record(axle_count=axle_count, axle_loads=loads)
        event = parse_wild_record(record)
        assert len(event.payload["axle_loads"]) == axle_count

    def test_unused_axle_slots_not_included(self) -> None:
        """
        Unused load slots (zero-padded) beyond axle_count must not appear
        in the normalised axle_loads list.
        """
        record = build_wild_record(
            axle_count=3,
            axle_loads=[11.1, 22.2, 33.3, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        event = parse_wild_record(record)
        assert len(event.payload["axle_loads"]) == 3
        assert abs(event.payload["axle_loads"][0] - 11.1) < 1e-4
        assert abs(event.payload["axle_loads"][2] - 33.3) < 1e-4

    def test_max_load_is_max_of_axle_loads(self) -> None:
        record = build_wild_record(
            axle_count=4,
            axle_loads=[80.0, 95.0, 70.0, 90.0, 0.0, 0.0, 0.0, 0.0],
        )
        event = parse_wild_record(record)
        assert abs(event.payload["max_load"] - 95.0) < 1e-4

    def test_train_id_null_stripped(self) -> None:
        """Null-padded train_id bytes are stripped from the decoded string."""
        record = build_wild_record(train_id="AB")
        event = parse_wild_record(record)
        assert event.payload["train_id"] == "AB"
        assert "\x00" not in event.payload["train_id"]


# ── 3. Dead-letter routing after 3 failures ───────────────────────────────────

class TestWildDeadLetterRouting:
    def _make_router(self, producer: MockKafkaProducer) -> DeadLetterRouter:
        return DeadLetterRouter(
            producer=producer,
            adapter_name="wild",
            adapter_version="1.0.0",
        )

    def test_three_failures_trigger_alert(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        bad_record = b"\xff" * WILD_RECORD_SIZE
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("wild-stream", bad_record)
        alerts = mock_producer.get_messages(ALERT_TOPIC)
        assert len(alerts) == 1
        assert alerts[0]["alertType"] == "LEGACY_ADAPTER_FAILURE"
        assert alerts[0]["adapter_name"] == "wild"

    def test_three_failures_publish_dead_letter(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        raw = bytes(range(64))  # 64-byte garbage record
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("wild-stream", raw)
        dead = mock_producer.get_messages(DEAD_LETTER_TOPIC)
        assert len(dead) == 1
        assert dead[0]["raw_payload_hex"] == raw.hex()
        assert dead[0]["adapter_name"] == "wild"

    def test_below_threshold_no_alert(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        for _ in range(FAILURE_THRESHOLD - 1):
            router.record_failure("wild-stream", b"\x00" * 64)
        assert len(mock_producer.messages[ALERT_TOPIC]) == 0

    def test_counter_resets_after_routing(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("wild-stream", b"\x00" * 64)
        assert router.failure_count("wild-stream") == 0

    def test_separate_sources_tracked_independently(
        self, mock_producer: MockKafkaProducer
    ) -> None:
        router = self._make_router(mock_producer)
        # Two failures for source A
        router.record_failure("wild-A", b"\x00" * 64)
        router.record_failure("wild-A", b"\x00" * 64)
        # One failure for source B — should not trigger anything
        router.record_failure("wild-B", b"\x00" * 64)
        assert len(mock_producer.messages[ALERT_TOPIC]) == 0
