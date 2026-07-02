"""
Unit tests for the OMRS stream adapter (Task 3.7).

Tests cover:
  1. Valid binary frame decode → correct CanonicalEvent fields
  2. 3 consecutive parse failures → dead-letter routing triggered
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

from omrs.omrs_adapter import parse_omrs_frame, read_frame
from shared.canonical_event import CanonicalEvent
from shared.dead_letter import (
    ALERT_TOPIC,
    DEAD_LETTER_TOPIC,
    DeadLetterRouter,
    FAILURE_THRESHOLD,
)
from tests.conftest import MockKafkaProducer, _build_omrs_payload, build_omrs_frame


# ── 1. Valid binary frame decode ──────────────────────────────────────────────

class TestOmrsFrameDecode:
    def test_sensor_type_is_wheel_load(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert event.sensorType == "wheel_load"

    def test_source_id_format(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert event.sourceId.startswith("omrs-")

    def test_asset_id_format(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert event.assetId.startswith("loco-")

    def test_payload_has_vibration_rms(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert "vibration_rms" in event.payload
        assert abs(event.payload["vibration_rms"] - 1.23) < 1e-6

    def test_payload_has_vibration_kurtosis(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert "vibration_kurtosis" in event.payload
        assert abs(event.payload["vibration_kurtosis"] - 3.45) < 1e-6

    def test_payload_has_temperature_bogie(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert "temperature_bogie" in event.payload
        assert abs(event.payload["temperature_bogie"] - 62.0) < 1e-6

    def test_payload_has_wheel_load_left(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert "wheel_load_left" in event.payload
        assert abs(event.payload["wheel_load_left"] - 98.5) < 1e-6

    def test_payload_has_wheel_load_right(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert "wheel_load_right" in event.payload
        assert abs(event.payload["wheel_load_right"] - 97.3) < 1e-6

    def test_payload_has_acoustic_emission_rms(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert "acoustic_emission_rms" in event.payload
        assert abs(event.payload["acoustic_emission_rms"] - 0.45) < 1e-6

    def test_payload_has_speed_kmh(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert "speed_kmh" in event.payload
        assert abs(event.payload["speed_kmh"] - 110.0) < 1e-6

    def test_schema_version(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        assert event.schema_version == "1.0.0"

    def test_event_id_is_uuid(self, omrs_payload_bytes: bytes) -> None:
        import uuid
        event = parse_omrs_frame(omrs_payload_bytes)
        uuid.UUID(event.eventId)

    def test_canonical_event_validates(self, omrs_payload_bytes: bytes) -> None:
        """Round-trip through Pydantic model_validate to confirm schema compliance."""
        event = parse_omrs_frame(omrs_payload_bytes)
        revalidated = CanonicalEvent.model_validate(event.model_dump())
        assert revalidated.sensorType == "wheel_load"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(Exception):
            parse_omrs_frame(b"not-json")

    def test_missing_required_field_raises(self) -> None:
        import json as _json
        payload = _json.dumps({"sensor_id": "S1", "train_id": "T1"}).encode()
        with pytest.raises((KeyError, ValueError)):
            parse_omrs_frame(payload)

    def test_different_sensor_ids_produce_different_source_ids(self) -> None:
        p1 = _build_omrs_payload(sensor_id="AAA")
        p2 = _build_omrs_payload(sensor_id="BBB")
        e1 = parse_omrs_frame(p1)
        e2 = parse_omrs_frame(p2)
        assert e1.sourceId != e2.sourceId

    def test_kafka_message_is_valid_json(self, omrs_payload_bytes: bytes) -> None:
        event = parse_omrs_frame(omrs_payload_bytes)
        msg = json.loads(event.to_kafka_message())
        assert msg["sensorType"] == "wheel_load"


# ── Frame header parsing (read_frame) via socket mock ─────────────────────────

class _FakeSocket:
    """Minimal socket-like object that yields bytes from a buffer."""

    def __init__(self, data: bytes) -> None:
        self._buf = data

    def recv(self, n: int) -> bytes:
        chunk = self._buf[:n]
        self._buf = self._buf[n:]
        return chunk


class TestOmrsReadFrame:
    def test_read_frame_strips_header_and_returns_payload(self) -> None:
        payload = b'{"sensor_id":"S1","train_id":"T1"}'
        frame = build_omrs_frame(payload)
        fake_sock = _FakeSocket(frame)
        result = read_frame(fake_sock)  # type: ignore[arg-type]
        assert result == payload

    def test_read_frame_eof_raises(self) -> None:
        from shared.socket_helpers import recv_exactly
        fake_sock = _FakeSocket(b"")
        with pytest.raises(EOFError):
            recv_exactly(fake_sock, 4)  # type: ignore[arg-type]


# ── 2. Dead-letter routing after 3 failures ───────────────────────────────────

class TestOmrsDeadLetterRouting:
    def _make_router(self, producer: MockKafkaProducer) -> DeadLetterRouter:
        return DeadLetterRouter(
            producer=producer,
            adapter_name="omrs",
            adapter_version="1.0.0",
        )

    def test_three_failures_trigger_alert(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("omrs-stream", b"bad-frame")
        alerts = mock_producer.get_messages(ALERT_TOPIC)
        assert len(alerts) == 1
        assert alerts[0]["alertType"] == "LEGACY_ADAPTER_FAILURE"
        assert alerts[0]["adapter_name"] == "omrs"

    def test_three_failures_publish_dead_letter(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        raw = b"\xde\xad\xbe\xef"
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("omrs-stream", raw)
        dead = mock_producer.get_messages(DEAD_LETTER_TOPIC)
        assert len(dead) == 1
        assert dead[0]["raw_payload_hex"] == raw.hex()
        assert dead[0]["adapter_name"] == "omrs"

    def test_below_threshold_no_alert(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        for _ in range(FAILURE_THRESHOLD - 1):
            router.record_failure("omrs-stream", b"bad")
        assert len(mock_producer.messages[ALERT_TOPIC]) == 0

    def test_counter_resets_after_routing(self, mock_producer: MockKafkaProducer) -> None:
        router = self._make_router(mock_producer)
        for _ in range(FAILURE_THRESHOLD):
            router.record_failure("omrs-stream", b"bad")
        assert router.failure_count("omrs-stream") == 0
