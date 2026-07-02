"""Unit tests for services.data_retention.retention_service."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from services.data_retention.retention_service import app, DEFAULT_RETENTION


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestPlaceForensicHold:
    @patch("services.data_retention.retention_service._insert_hold")
    def test_place_hold_returns_record(self, mock_insert, client):
        payload = {
            "alertId": "alert-123",
            "placedBy": "officer-A",
            "reason": "Investigation ongoing",
        }
        resp = client.post("/api/v1/retention/holds", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["alertId"] == "alert-123"
        assert data["placedBy"] == "officer-A"
        assert data["active"] is True
        assert "holdId" in data
        assert "placedAt" in data
        mock_insert.assert_called_once()

    @patch("services.data_retention.retention_service._insert_hold")
    def test_place_hold_without_alert_id(self, mock_insert, client):
        payload = {
            "placedBy": "officer-B",
            "reason": "Proactive hold",
        }
        resp = client.post("/api/v1/retention/holds", json=payload)
        assert resp.status_code == 200
        assert resp.json()["alertId"] is None

    def test_place_hold_missing_required_fields(self, client):
        resp = client.post("/api/v1/retention/holds", json={"alertId": "x"})
        assert resp.status_code == 422


class TestReleaseForensicHold:
    @patch("services.data_retention.retention_service._release_hold")
    def test_release_hold(self, mock_release, client):
        resp = client.delete(
            "/api/v1/retention/holds/hold-456?released_by=officer-C"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"
        mock_release.assert_called_once_with("hold-456", "officer-C")


class TestMonthlyComplianceReport:
    @patch("services.data_retention.retention_service._count_active_holds", return_value=5)
    def test_report_structure(self, mock_count, client):
        resp = client.get("/api/v1/retention/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "generatedAt" in data
        assert "categories" in data
        assert data["activeHolds"] == 5
        for cat in DEFAULT_RETENTION:
            assert cat in data["categories"]

    @patch("services.data_retention.retention_service._count_active_holds", side_effect=Exception("db error"))
    def test_report_handles_db_error(self, mock_count, client):
        resp = client.get("/api/v1/retention/report")
        assert resp.status_code == 200
        assert resp.json()["activeHolds"] == 0


class TestRunRetentionCycle:
    def test_retention_cycle_processes_all_categories(self, client):
        resp = client.post("/api/v1/retention/run-cycle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert "model_artifacts" in data["results"]
        assert data["results"]["model_artifacts"] == "skipped (indefinite)"
        for cat, ttl in DEFAULT_RETENTION.items():
            if ttl is not None:
                assert f"TTL={ttl}d" in data["results"][cat]
