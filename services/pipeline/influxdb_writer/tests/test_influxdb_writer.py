"""
Tests for InfluxDB Writer Service
===================================
Covers:
  - Successful write to InfluxDB
  - Retry on first failure (succeeds on second attempt)
  - STORAGE_WRITE_FAILURE emitted after 3 consecutive failures
  - Event never discarded — persisted to SQLite failure queue after exhaustion

Req 1 C4/C5/C8: Write, retry, alert, persist.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to locate the module under test from any working directory
# ---------------------------------------------------------------------------
import sys
import pathlib

# Add the influxdb_writer directory to path so we can import directly
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from influxdb_writer import (
    RETRY_DELAYS,
    FailureQueue,
    InfluxDBWriter,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_event(
    sensor_type: str = "vibration",
    asset_id: str = "zone-a-track-042",
) -> dict:
    """Return a minimal valid canonical event dict."""
    return {
        "eventId": "11111111-1111-1111-1111-111111111111",
        "sourceId": "edge-node-test-001",
        "sensorType": sensor_type,
        "assetId": asset_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sequence": 1,
        "payload": {"rms": 0.12, "unit": "g"},
        "quality_flags": {
            "interpolated": False,
            "interpolation_pct": 0.0,
            "clock_reliable": True,
            "drift_ms": 5.0,
        },
        "schema_version": "1.0.0",
    }


@pytest.fixture()
def failure_queue(tmp_path):
    """Return a FailureQueue backed by a temp SQLite DB."""
    db_path = str(tmp_path / "failure_queue.db")
    return FailureQueue(db_path=db_path)


@pytest.fixture()
def mock_influx_client():
    """Return a mock InfluxDBClient with a write_api that records calls."""
    client = MagicMock()
    write_api = MagicMock()
    client.write_api.return_value = write_api
    return client, write_api


@pytest.fixture()
def mock_kafka_producer():
    producer = MagicMock()
    producer.send.return_value = MagicMock()
    return producer


@pytest.fixture()
def writer(mock_influx_client, mock_kafka_producer, failure_queue):
    """Return an InfluxDBWriter wired to mocks."""
    client, _ = mock_influx_client
    return InfluxDBWriter(
        influx_client=client,
        kafka_producer=mock_kafka_producer,
        failure_queue=failure_queue,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSuccessfulWrite:
    """write_event returns True on first successful write."""

    def test_successful_write_returns_true(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        # write_api.write does not raise — simulates success
        write_api.write.return_value = None

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        result = writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        assert result is True

    def test_successful_write_calls_write_api_once(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.return_value = None

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        assert write_api.write.call_count == 1

    def test_successful_write_does_not_enqueue_in_failure_queue(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.return_value = None

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        assert failure_queue.depth() == 0

    def test_successful_write_does_not_emit_alert(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.return_value = None

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        mock_kafka_producer.send.assert_not_called()


class TestRetryOnFirstFailure:
    """write_event retries and succeeds on the second attempt."""

    def test_retry_on_first_failure_returns_true(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        # Fail once, then succeed
        write_api.write.side_effect = [Exception("transient"), None]

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        # Patch time.sleep to speed up test
        with patch("influxdb_writer.time.sleep"):
            result = writer.write_event(
                _make_event(), source_topic="track.sensor.vibration_validated"
            )

        assert result is True

    def test_retry_calls_write_twice(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = [Exception("transient"), None]

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        assert write_api.write.call_count == 2

    def test_retry_on_first_failure_no_failure_queue_entry(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = [Exception("transient"), None]

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        assert failure_queue.depth() == 0


class TestStorageWriteFailureAfterThreeAttempts:
    """After 3 consecutive failures, STORAGE_WRITE_FAILURE is emitted."""

    def test_returns_false_after_exhaustion(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = Exception("persistent failure")

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            result = writer.write_event(
                _make_event(), source_topic="track.sensor.vibration_validated"
            )

        assert result is False

    def test_write_api_called_three_times(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = Exception("persistent failure")

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        assert write_api.write.call_count == len(RETRY_DELAYS)

    def test_storage_write_failure_alert_emitted(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = Exception("persistent failure")

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        # KafkaProducer.send must have been called with the alerts topic
        mock_kafka_producer.send.assert_called_once()
        topic_arg = mock_kafka_producer.send.call_args[0][0]
        assert topic_arg == "monitoring.alerts"

    def test_storage_write_failure_alert_type(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = Exception("persistent failure")

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        call_kwargs = mock_kafka_producer.send.call_args[1]
        alert_bytes: bytes = call_kwargs["value"]
        alert = json.loads(alert_bytes.decode("utf-8"))
        assert alert["alertType"] == "STORAGE_WRITE_FAILURE"

    def test_storage_write_failure_alert_contains_event_id(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = Exception("persistent failure")

        event = _make_event()
        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            writer.write_event(event, source_topic="track.sensor.vibration_validated")

        alert_bytes = mock_kafka_producer.send.call_args[1]["value"]
        alert = json.loads(alert_bytes.decode("utf-8"))
        assert alert["eventId"] == event["eventId"]


class TestEventNotDiscarded:
    """After 3 failures, event is stored in the SQLite failure queue."""

    def test_event_stored_in_failure_queue(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = Exception("persistent failure")

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            writer.write_event(_make_event(), source_topic="track.sensor.vibration_validated")

        assert failure_queue.depth() == 1

    def test_failure_queue_contains_correct_event_id(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        client, write_api = mock_influx_client
        write_api.write.side_effect = Exception("persistent failure")

        event = _make_event()
        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        with patch("influxdb_writer.time.sleep"):
            writer.write_event(event, source_topic="track.sensor.vibration_validated")

        with sqlite3.connect(failure_queue._db_path) as conn:
            row = conn.execute(
                "SELECT event_id, payload_json FROM failed_events"
            ).fetchone()

        assert row is not None
        assert row[0] == event["eventId"]
        stored = json.loads(row[1])
        assert stored["assetId"] == event["assetId"]

    def test_multiple_failures_all_stored(
        self, mock_influx_client, mock_kafka_producer, failure_queue
    ):
        """Each exhausted write stores exactly one entry — no double-queuing."""
        client, write_api = mock_influx_client
        write_api.write.side_effect = Exception("persistent failure")

        writer = InfluxDBWriter(client, mock_kafka_producer, failure_queue)
        for _ in range(3):
            with patch("influxdb_writer.time.sleep"):
                writer.write_event(
                    _make_event(), source_topic="track.sensor.vibration_validated"
                )

        assert failure_queue.depth() == 3
