"""Unit tests for services.security.privilege_escalation_handler."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from services.security.privilege_escalation_handler import (
    app,
    _extract_field,
    _terminate_container_after_delay,
)


@pytest.fixture
def client():
    with patch("services.security.privilege_escalation_handler._startup"):
        return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestExtractField:
    def test_extract_known_field(self):
        output = "user=root container=nginx pod=web-abc123 syscall=ptrace"
        assert _extract_field(output, "container=") == "nginx"
        assert _extract_field(output, "pod=") == "web-abc123"
        assert _extract_field(output, "syscall=") == "ptrace"

    def test_extract_last_field_no_trailing_space(self):
        output = "user=root container=nginx"
        assert _extract_field(output, "container=") == "nginx"

    def test_extract_missing_field(self):
        assert _extract_field("user=root", "container=") == "unknown"

    def test_extract_empty_output(self):
        assert _extract_field("", "container=") == "unknown"


class TestFalcoAlertHandler:
    @patch("services.security.privilege_escalation_handler._emit_alert")
    @patch("services.security.privilege_escalation_handler.threading.Thread")
    def test_handle_privilege_escalation(self, mock_thread, mock_emit, client):
        mock_thread_inst = MagicMock()
        mock_thread.return_value = mock_thread_inst
        payload = {
            "rule": "PRIVILEGE_ESCALATION_ATTEMPT",
            "priority": "CRITICAL",
            "output": "container=malicious pod=evil-pod syscall=setuid",
            "output_fields": {
                "container.name": "malicious",
                "k8s.pod.name": "evil-pod",
                "syscall.type": "setuid",
            },
        }
        resp = client.post("/falco/alert", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["handled"] is True
        assert "alertId" in data
        assert data["terminationScheduled"] is True
        mock_emit.assert_called_once()
        mock_thread_inst.start.assert_called_once()

    def test_non_escalation_event_ignored(self, client):
        payload = {
            "rule": "FILE_OPEN",
            "priority": "WARNING",
            "output": "normal operation",
            "output_fields": {},
        }
        resp = client.post("/falco/alert", json=payload)
        assert resp.status_code == 200
        assert resp.json()["handled"] is False

    def test_critical_priority_is_handled(self, client):
        with patch("services.security.privilege_escalation_handler._emit_alert"):
            with patch("services.security.privilege_escalation_handler.threading.Thread") as mock_t:
                mock_t.return_value = MagicMock()
                payload = {
                    "rule": "SOME_CRITICAL_RULE",
                    "priority": "CRITICAL",
                    "output": "suspicious activity",
                    "output_fields": {},
                }
                resp = client.post("/falco/alert", json=payload)
                assert resp.json()["handled"] is True

    def test_invalid_json_body(self, client):
        resp = client.post(
            "/falco/alert",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    @patch("services.security.privilege_escalation_handler._emit_alert")
    @patch("services.security.privilege_escalation_handler.threading.Thread")
    def test_extracts_from_output_when_fields_missing(self, mock_thread, mock_emit, client):
        mock_thread.return_value = MagicMock()
        payload = {
            "rule": "PRIVILEGE_ESCALATION",
            "priority": "CRITICAL",
            "output": "container=hacked pod=my-pod syscall=execve",
            "output_fields": {},  # empty fields
        }
        resp = client.post("/falco/alert", json=payload)
        data = resp.json()
        assert data["handled"] is True
        # Verify the emitted event parsed container/pod from output string
        call_args = mock_emit.call_args[0][0]
        assert call_args["containerName"] == "hacked"
        assert call_args["podName"] == "my-pod"


class TestTerminateContainerAfterDelay:
    @patch("services.security.privilege_escalation_handler.subprocess.run")
    def test_terminate_calls_kubectl(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _terminate_container_after_delay("my-pod", "my-container", 0)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "kubectl" in args
        assert "my-pod" in args

    def test_terminate_unknown_pod_skips(self):
        # Should log warning but not call kubectl
        _terminate_container_after_delay("unknown", "container", 0)

    @patch("services.security.privilege_escalation_handler.subprocess.run", side_effect=FileNotFoundError)
    def test_terminate_kubectl_not_found(self, mock_run):
        _terminate_container_after_delay("pod-1", "container-1", 0)
