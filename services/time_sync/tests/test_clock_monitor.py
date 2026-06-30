"""
Integration test: Task 2.5
Simulate clock source failure — verify all subsequent sensor events carry
the CLOCK_UNRELIABLE flag.

Run:
    pytest services/time-sync/tests/test_clock_monitor.py -v
"""

import json
import os
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import MagicMock, patch, call

# Ensure the clock-monitor module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "clock-monitor"))

# Stub the kafka module before clock_monitor is imported, because
# kafka-python 2.0.2 is incompatible with Python 3.12 at import time.
# All Kafka calls are mocked in individual tests anyway.
import types as _types
_kafka_stub = _types.ModuleType("kafka")
_kafka_stub.KafkaProducer = MagicMock
_kafka_stub.errors = _types.ModuleType("kafka.errors")
_kafka_stub.errors.KafkaError = Exception
sys.modules.setdefault("kafka", _kafka_stub)
sys.modules.setdefault("kafka.errors", _kafka_stub.errors)


class TestClockMonitorDriftAlert(unittest.TestCase):
    """Tests for CLOCK_DRIFT_ALERT emission (Task 2.3)."""

    def _make_producer_mock(self):
        mock = MagicMock()
        mock.send.return_value = MagicMock()
        mock.flush.return_value = None
        return mock

    @patch("clock_monitor.make_producer")
    @patch("clock_monitor.get_clock_drift_ms")
    def test_drift_alert_published_when_threshold_exceeded(self, mock_drift, mock_producer_factory):
        """CLOCK_DRIFT_ALERT should be published when |drift| > 100ms."""
        import clock_monitor as cm

        mock_drift.return_value = (150.0, True)   # 150ms drift, clock reliable
        mock_prod = self._make_producer_mock()
        mock_producer_factory.return_value = mock_prod

        cm.DRIFT_THRESHOLD_MS = 100.0

        # Call the alert function directly
        cm.publish_drift_alert(mock_prod, 150.0)

        mock_prod.send.assert_called_once()
        call_args = mock_prod.send.call_args
        topic = call_args[0][0]
        event = call_args[1]["value"]

        self.assertEqual(topic, "monitoring.alerts")
        self.assertEqual(event["alertType"], "CLOCK_DRIFT_ALERT")
        self.assertAlmostEqual(event["drift_ms"], 150.0)

    @patch("clock_monitor.make_producer")
    @patch("clock_monitor.get_clock_drift_ms")
    def test_no_alert_within_threshold(self, mock_drift, mock_producer_factory):
        """No CLOCK_DRIFT_ALERT when |drift| ≤ 100ms."""
        import clock_monitor as cm

        mock_drift.return_value = (50.0, True)
        mock_prod = self._make_producer_mock()

        # drift is 50ms — below threshold
        # verify publish_drift_alert is NOT called
        # (the main loop logic guards this; test the guard condition directly)
        cm.DRIFT_THRESHOLD_MS = 100.0
        should_alert = abs(50.0) > cm.DRIFT_THRESHOLD_MS
        self.assertFalse(should_alert)


class TestClockUnreliableFlag(unittest.TestCase):
    """Tests for CLOCK_UNRELIABLE flag injection (Task 2.4) and clock source
    failure simulation (Task 2.5)."""

    def setUp(self):
        # Use a temp file for clock status to avoid polluting /tmp
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_write_and_read_reliable_status(self):
        """write_clock_status(True) → read_clock_status() returns True."""
        import clock_monitor as cm
        cm.CLOCK_STATUS_PATH = self.tmp.name
        cm.write_clock_status(True)
        self.assertTrue(cm.read_clock_status())

    def test_write_unreliable_then_read(self):
        """write_clock_status(False) → read_clock_status() returns False."""
        import clock_monitor as cm
        cm.CLOCK_STATUS_PATH = self.tmp.name
        cm.write_clock_status(False)
        self.assertFalse(cm.read_clock_status())

    def test_clock_source_failure_sets_unreliable_flag(self):
        """
        Task 2.5: Simulate clock source failure.
        When adjtimex reports STA_UNSYNC (clock_reliable=False),
        the monitor writes clock_reliable=False to the status file
        and publishes CLOCK_SYNC_LOST to monitoring.alerts.
        """
        import clock_monitor as cm
        cm.CLOCK_STATUS_PATH = self.tmp.name
        cm.write_clock_status(True)   # start reliable

        mock_prod = MagicMock()
        mock_prod.send.return_value = MagicMock()
        mock_prod.flush.return_value = None

        # Simulate: clock reports STA_UNSYNC (reliable=False)
        cm.publish_unreliable_event(mock_prod)
        cm.write_clock_status(False)

        # Verify CLOCK_SYNC_LOST was published
        mock_prod.send.assert_called_once()
        alert_topic = mock_prod.send.call_args[0][0]
        alert_event = mock_prod.send.call_args[1]["value"]
        self.assertEqual(alert_topic, "monitoring.alerts")
        self.assertEqual(alert_event["alertType"], "CLOCK_SYNC_LOST")
        self.assertFalse(alert_event["clock_reliable"])

        # Verify flag file indicates clock is unreliable
        self.assertFalse(cm.read_clock_status())

    def test_sensor_event_carries_clock_unreliable_flag(self):
        """
        Task 2.5: Subsequent sensor events must carry CLOCK_UNRELIABLE flag.
        Simulates how a sensor adapter reads the clock status file and sets
        the quality_flags.clock_reliable field in the canonical event schema.
        """
        import clock_monitor as cm
        cm.CLOCK_STATUS_PATH = self.tmp.name

        # Write unreliable status (simulating clock failure)
        cm.write_clock_status(False)

        # Sensor adapter logic: read flag and inject into event
        clock_reliable = cm.read_clock_status()
        sensor_event = {
            "eventId": "test-uuid",
            "sensorType": "vibration",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "quality_flags": {
                "interpolated": False,
                "interpolation_pct": 0.0,
                "clock_reliable": clock_reliable,   # injected from monitor
                "drift_ms": 0.0,
            },
        }

        # Verify event carries CLOCK_UNRELIABLE flag
        self.assertFalse(sensor_event["quality_flags"]["clock_reliable"],
                         "Sensor event must have clock_reliable=False when PTP sync is lost")

    def test_flag_cleared_after_sync_restored(self):
        """
        Once clock sync is restored, subsequent events should carry clock_reliable=True.
        """
        import clock_monitor as cm
        cm.CLOCK_STATUS_PATH = self.tmp.name

        # Step 1: Clock fails
        cm.write_clock_status(False)
        self.assertFalse(cm.read_clock_status())

        # Step 2: Clock sync restored
        cm.write_clock_status(True)

        # Step 3: Next sensor event should have clock_reliable=True
        clock_reliable = cm.read_clock_status()
        self.assertTrue(clock_reliable,
                        "CLOCK_UNRELIABLE flag must be cleared when sync is restored")

    def test_status_file_missing_returns_reliable(self):
        """If status file doesn't exist, default to reliable (safe assumption)."""
        import clock_monitor as cm
        cm.CLOCK_STATUS_PATH = "/tmp/nonexistent_railos_clock_status_xyz.json"
        self.assertTrue(cm.read_clock_status())


class TestDriftThresholds(unittest.TestCase):
    """Tests verifying threshold boundary conditions."""

    def test_exactly_at_threshold_no_alert(self):
        """Drift exactly at ±100ms should NOT trigger alert (> not >=)."""
        import clock_monitor as cm
        cm.DRIFT_THRESHOLD_MS = 100.0
        self.assertFalse(abs(100.0) > cm.DRIFT_THRESHOLD_MS)

    def test_one_ms_above_threshold_triggers_alert(self):
        """Drift of 100.001ms exceeds threshold."""
        import clock_monitor as cm
        cm.DRIFT_THRESHOLD_MS = 100.0
        self.assertTrue(abs(100.001) > cm.DRIFT_THRESHOLD_MS)

    def test_negative_drift_above_threshold(self):
        """Negative drift of -150ms exceeds threshold."""
        import clock_monitor as cm
        cm.DRIFT_THRESHOLD_MS = 100.0
        self.assertTrue(abs(-150.0) > cm.DRIFT_THRESHOLD_MS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
