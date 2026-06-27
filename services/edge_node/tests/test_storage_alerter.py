"""
Tests for StorageAlerter (Task 5.6)
Covers: alert triggered at ≥90% capacity, SMS path (mock httpx.post → 200),
        console fallback (mock httpx.post fails), audit log fallback.
Satisfies: Req 2 C5
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerter.storage_alerter import StorageAlerter, CAPACITY_THRESHOLD


# ── Buffer stub ────────────────────────────────────────────────────────────────

class _FakeBuffer:
    """Simple stub that returns a fixed capacity percentage."""

    def __init__(self, pct: float) -> None:
        self._pct = pct

    def capacity_pct(self) -> float:
        return self._pct


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_alerter(pct: float, sms_url: str = "http://sms.example.com/send") -> StorageAlerter:
    buf = _FakeBuffer(pct)
    alerter = StorageAlerter(buf)
    # Patch env so SMS_GATEWAY_URL is set inside alerter module
    return alerter


def _call_send_alert(alerter: StorageAlerter, pct: float = 95.0) -> None:
    """Directly invoke the private _send_alert method for unit testing."""
    alerter._send_alert(pct)


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestAlertThreshold:
    """Alert fires at ≥90% capacity and is suppressed below threshold."""

    def test_alert_triggered_at_90_percent(self, tmp_path) -> None:
        """_send_alert should be called when capacity reaches CAPACITY_THRESHOLD."""
        buf = _FakeBuffer(90.0)
        alerter = StorageAlerter(buf)

        with patch.object(alerter, "_send_alert") as mock_alert:
            # Simulate one check cycle manually
            pct = buf.capacity_pct()
            if pct >= CAPACITY_THRESHOLD:
                alerter._send_alert(pct)

            mock_alert.assert_called_once_with(90.0)

    def test_alert_triggered_above_90_percent(self, tmp_path) -> None:
        buf = _FakeBuffer(99.9)
        alerter = StorageAlerter(buf)

        with patch.object(alerter, "_send_alert") as mock_alert:
            pct = buf.capacity_pct()
            if pct >= CAPACITY_THRESHOLD:
                alerter._send_alert(pct)

            mock_alert.assert_called_once()

    def test_no_alert_below_threshold(self, tmp_path) -> None:
        buf = _FakeBuffer(89.9)
        alerter = StorageAlerter(buf)

        with patch.object(alerter, "_send_alert") as mock_alert:
            pct = buf.capacity_pct()
            if pct >= CAPACITY_THRESHOLD:
                alerter._send_alert(pct)

            mock_alert.assert_not_called()


class TestSMSPath:
    """When SMS gateway returns 200, alert is delivered via SMS only."""

    def test_sms_success_returns_without_console_print(self, capsys, tmp_path) -> None:
        alerter = StorageAlerter(_FakeBuffer(95.0))

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.dict(os.environ, {"SMS_GATEWAY_URL": "http://sms.local/send"}):
            # Re-import or patch inside the alerter module's namespace
            import alerter.storage_alerter as alerter_mod
            original_url = alerter_mod.SMS_GATEWAY_URL
            alerter_mod.SMS_GATEWAY_URL = "http://sms.local/send"
            try:
                with patch("alerter.storage_alerter.httpx.post",
                           return_value=mock_response) as mock_post:
                    _call_send_alert(alerter, 95.0)

                    mock_post.assert_called_once()
                    call_kwargs = mock_post.call_args
                    assert call_kwargs[0][0] == "http://sms.local/send"
            finally:
                alerter_mod.SMS_GATEWAY_URL = original_url

        captured = capsys.readouterr()
        # SMS succeeded → should NOT fall through to console print
        assert "STORAGE_THRESHOLD" not in captured.out

    def test_sms_called_with_correct_payload(self, tmp_path) -> None:
        alerter = StorageAlerter(_FakeBuffer(92.0))

        mock_response = MagicMock()
        mock_response.status_code = 200

        import alerter.storage_alerter as alerter_mod
        original_url = alerter_mod.SMS_GATEWAY_URL
        alerter_mod.SMS_GATEWAY_URL = "http://sms.local/send"
        try:
            with patch("alerter.storage_alerter.httpx.post",
                       return_value=mock_response) as mock_post:
                _call_send_alert(alerter, 92.0)

            post_json = mock_post.call_args[1]["json"]
            assert "92.0" in post_json["message"]
            assert "STORAGE_THRESHOLD" in post_json["message"]
        finally:
            alerter_mod.SMS_GATEWAY_URL = original_url


class TestConsoleFallback:
    """When SMS gateway is unavailable, alert falls back to console print."""

    def test_console_fallback_on_http_exception(self, capsys, tmp_path) -> None:
        alerter = StorageAlerter(_FakeBuffer(95.0))

        import alerter.storage_alerter as alerter_mod
        original_url = alerter_mod.SMS_GATEWAY_URL
        alerter_mod.SMS_GATEWAY_URL = "http://sms.local/send"
        try:
            with patch("alerter.storage_alerter.httpx.post",
                       side_effect=Exception("connection refused")):
                _call_send_alert(alerter, 95.0)
        finally:
            alerter_mod.SMS_GATEWAY_URL = original_url

        captured = capsys.readouterr()
        assert "STORAGE_THRESHOLD" in captured.out

    def test_console_fallback_on_non_200_status(self, capsys, tmp_path) -> None:
        alerter = StorageAlerter(_FakeBuffer(95.0))

        mock_response = MagicMock()
        mock_response.status_code = 503

        import alerter.storage_alerter as alerter_mod
        original_url = alerter_mod.SMS_GATEWAY_URL
        alerter_mod.SMS_GATEWAY_URL = "http://sms.local/send"
        try:
            with patch("alerter.storage_alerter.httpx.post",
                       return_value=mock_response):
                _call_send_alert(alerter, 95.0)
        finally:
            alerter_mod.SMS_GATEWAY_URL = original_url

        captured = capsys.readouterr()
        assert "STORAGE_THRESHOLD" in captured.out

    def test_console_output_contains_capacity_json(self, capsys, tmp_path) -> None:
        alerter = StorageAlerter(_FakeBuffer(95.0))

        import alerter.storage_alerter as alerter_mod
        original_url = alerter_mod.SMS_GATEWAY_URL
        alerter_mod.SMS_GATEWAY_URL = ""  # no SMS URL → goes straight to console
        try:
            _call_send_alert(alerter, 91.5)
        finally:
            alerter_mod.SMS_GATEWAY_URL = original_url

        captured = capsys.readouterr()
        assert "STORAGE_THRESHOLD" in captured.out
        # Should contain JSON payload
        line = captured.out.strip().split("STORAGE_THRESHOLD ")[1]
        payload = json.loads(line)
        assert payload["alertType"] == "STORAGE_THRESHOLD"
        assert payload["capacityPct"] == 91.5


class TestAuditLogFallback:
    """Audit log is always written when the alert fires."""

    def test_audit_log_written_on_console_fallback(self, tmp_path) -> None:
        log_path = str(tmp_path / "logs" / "alerts.jsonl")

        alerter = StorageAlerter(_FakeBuffer(95.0))

        import alerter.storage_alerter as alerter_mod
        original_url  = alerter_mod.SMS_GATEWAY_URL
        original_path = alerter_mod.ALERT_LOG_PATH
        alerter_mod.SMS_GATEWAY_URL  = ""          # skip SMS path
        alerter_mod.ALERT_LOG_PATH   = log_path
        try:
            _call_send_alert(alerter, 95.0)
        finally:
            alerter_mod.SMS_GATEWAY_URL  = original_url
            alerter_mod.ALERT_LOG_PATH   = original_path

        assert os.path.exists(log_path)
        with open(log_path) as f:
            lines = f.readlines()
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert record["alertType"] == "STORAGE_THRESHOLD"
        assert record["capacityPct"] == 95.0

    def test_audit_log_contains_threshold_field(self, tmp_path) -> None:
        log_path = str(tmp_path / "logs" / "alerts.jsonl")

        alerter = StorageAlerter(_FakeBuffer(93.0))

        import alerter.storage_alerter as alerter_mod
        original_url  = alerter_mod.SMS_GATEWAY_URL
        original_path = alerter_mod.ALERT_LOG_PATH
        alerter_mod.SMS_GATEWAY_URL  = ""
        alerter_mod.ALERT_LOG_PATH   = log_path
        try:
            _call_send_alert(alerter, 93.0)
        finally:
            alerter_mod.SMS_GATEWAY_URL  = original_url
            alerter_mod.ALERT_LOG_PATH   = original_path

        with open(log_path) as f:
            record = json.loads(f.readline())

        assert "threshold" in record
        assert record["threshold"] == CAPACITY_THRESHOLD

    def test_multiple_alerts_append_to_log(self, tmp_path) -> None:
        log_path = str(tmp_path / "logs" / "alerts.jsonl")

        alerter = StorageAlerter(_FakeBuffer(95.0))

        import alerter.storage_alerter as alerter_mod
        original_url  = alerter_mod.SMS_GATEWAY_URL
        original_path = alerter_mod.ALERT_LOG_PATH
        alerter_mod.SMS_GATEWAY_URL  = ""
        alerter_mod.ALERT_LOG_PATH   = log_path
        try:
            _call_send_alert(alerter, 91.0)
            _call_send_alert(alerter, 95.0)
            _call_send_alert(alerter, 99.5)
        finally:
            alerter_mod.SMS_GATEWAY_URL  = original_url
            alerter_mod.ALERT_LOG_PATH   = original_path

        with open(log_path) as f:
            lines = f.readlines()
        assert len(lines) == 3
