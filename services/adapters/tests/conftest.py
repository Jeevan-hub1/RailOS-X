"""
Test fixtures for RailOS legacy adapter unit tests (Task 3.7).

Provides:
  - MockKafkaProducer      : records sent messages; no real Kafka required
  - ntes_sample_json       : valid NTES train-position JSON record
  - omrs_binary_frame      : valid OMRS length-prefixed binary frame
  - wild_binary_record     : valid WILD 64-byte struct record
"""

from __future__ import annotations

import json
import struct
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import pytest


# ── Mock Kafka Producer ────────────────────────────────────────────────────────

class MockKafkaProducer:
    """
    Minimal Kafka producer mock.

    Records every ``send(topic, value=...)`` call so tests can assert on
    the messages that would have been published, without a real broker.
    """

    def __init__(self) -> None:
        # topic → list of raw value bytes
        self.messages: dict[str, list[bytes]] = defaultdict(list)
        self._flush_count: int = 0

    def send(self, topic: str, value: bytes | None = None, **kwargs: Any) -> None:
        if value is not None:
            self.messages[topic].append(value)

    def flush(self, timeout: float = 5.0) -> None:
        self._flush_count += 1

    def get_messages(self, topic: str) -> list[dict[str, Any]]:
        """Decode all JSON messages sent to *topic*."""
        return [json.loads(m) for m in self.messages[topic]]


@pytest.fixture
def mock_producer() -> MockKafkaProducer:
    """Return a fresh MockKafkaProducer for each test."""
    return MockKafkaProducer()


# ── NTES sample fixture ────────────────────────────────────────────────────────

@pytest.fixture
def ntes_sample_json() -> dict[str, Any]:
    """
    A single valid NTES train-position JSON record as a Python dict.
    Matches the schema expected by ``parse_ntes_record()``.
    """
    return {
        "train_number": "12345",
        "latitude": 28.6139,
        "longitude": 77.2090,
        "speed_kmh": 95.5,
        "station_code": "NDLS",
        "timestamp": "2024-06-01T10:30:00+00:00",
        "sequence_no": 42,
    }


# ── OMRS binary frame fixture ──────────────────────────────────────────────────

def _build_omrs_payload(
    sensor_id: str = "S001",
    train_id: str = "T100",
    vibration_rms: float = 1.23,
    vibration_kurtosis: float = 3.45,
    temperature_bogie: float = 62.0,
    wheel_load_left: float = 98.5,
    wheel_load_right: float = 97.3,
    acoustic_emission_rms: float = 0.45,
    speed_kmh: float = 110.0,
    sequence_no: int = 1,
) -> bytes:
    """Return JSON bytes representing a valid OMRS sensor payload."""
    record = {
        "sensor_id": sensor_id,
        "train_id": train_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sequence_no": sequence_no,
        "vibration_rms": vibration_rms,
        "vibration_kurtosis": vibration_kurtosis,
        "temperature_bogie": temperature_bogie,
        "wheel_load_left": wheel_load_left,
        "wheel_load_right": wheel_load_right,
        "acoustic_emission_rms": acoustic_emission_rms,
        "speed_kmh": speed_kmh,
    }
    return json.dumps(record).encode("utf-8")


def build_omrs_frame(payload: bytes) -> bytes:
    """Wrap *payload* in a 4-byte big-endian length-prefixed frame."""
    header = struct.pack(">I", len(payload))
    return header + payload


@pytest.fixture
def omrs_payload_bytes() -> bytes:
    """Raw JSON payload bytes for a valid OMRS record (no frame header)."""
    return _build_omrs_payload()


@pytest.fixture
def omrs_binary_frame() -> bytes:
    """
    Complete OMRS length-prefixed binary frame:
      [4-byte big-endian length][JSON payload bytes]
    """
    payload = _build_omrs_payload()
    return build_omrs_frame(payload)


# ── WILD binary record fixture ─────────────────────────────────────────────────

# WILD record format (64 bytes, big-endian):
#   train_id[8s] + timestamp_ms[Q] + axle_count[B] + pad[3x]
#   + load_per_axle[8f] + trailing_pad[12x]
_WILD_FORMAT = ">8sQB3x8f12x"
assert struct.calcsize(_WILD_FORMAT) == 64


def build_wild_record(
    train_id: str = "TR56789",
    timestamp_ms: int | None = None,
    axle_count: int = 4,
    axle_loads: list[float] | None = None,
) -> bytes:
    """
    Build a valid 64-byte WILD binary record.

    *axle_loads* must have at least *axle_count* values; unused axle slots
    are padded with 0.0.
    """
    if timestamp_ms is None:
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if axle_loads is None:
        axle_loads = [95.0, 97.5, 96.0, 98.2, 0.0, 0.0, 0.0, 0.0]
    # Ensure exactly 8 load values
    loads_8: list[float] = (axle_loads + [0.0] * 8)[:8]
    # Encode train_id as 8 bytes, null-padded
    train_id_bytes = train_id.encode("utf-8")[:8].ljust(8, b"\x00")
    return struct.pack(_WILD_FORMAT, train_id_bytes, timestamp_ms, axle_count, *loads_8)


@pytest.fixture
def wild_binary_record() -> bytes:
    """A valid 64-byte WILD binary record fixture."""
    return build_wild_record()
