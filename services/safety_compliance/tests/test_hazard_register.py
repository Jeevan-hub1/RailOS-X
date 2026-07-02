"""Unit tests for services.safety_compliance.hazard_register."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from services.safety_compliance.hazard_register import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestCreateHazard:
    @patch("services.safety_compliance.hazard_register._insert_hazard")
    def test_create_hazard_returns_record(self, mock_insert, client):
        payload = {
            "description": "Rail crack detected on corridor B",
            "subsystem": "defect_detector",
            "likelihood": "Medium",
            "severity": "Major",
            "mitigation": "Speed restriction applied",
            "createdBy": "engineer-1",
        }
        resp = client.post("/api/v1/hazards", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == payload["description"]
        assert data["subsystem"] == "defect_detector"
        assert data["approval_status"] == "Open"
        assert data["hazard_id"].startswith("HAZ-")
        assert "revision_id" in data
        assert "created_at" in data
        mock_insert.assert_called_once()

    @patch("services.safety_compliance.hazard_register._insert_hazard")
    def test_create_hazard_with_custom_id(self, mock_insert, client):
        payload = {
            "hazardId": "HAZ-CUSTOM-001",
            "description": "Track subsidence",
            "subsystem": "digital_twin",
            "likelihood": "Low",
            "severity": "Catastrophic",
            "mitigation": "Emergency closure",
            "createdBy": "engineer-2",
        }
        resp = client.post("/api/v1/hazards", json=payload)
        assert resp.status_code == 200
        assert resp.json()["hazard_id"] == "HAZ-CUSTOM-001"

    def test_create_hazard_missing_fields(self, client):
        resp = client.post("/api/v1/hazards", json={"description": "incomplete"})
        assert resp.status_code == 422

    @patch("services.safety_compliance.hazard_register._insert_hazard")
    def test_default_residual_risk_and_approval(self, mock_insert, client):
        payload = {
            "description": "Signal failure",
            "subsystem": "kavach",
            "likelihood": "High",
            "severity": "Major",
            "mitigation": "Fallback to manual",
            "createdBy": "officer-X",
        }
        resp = client.post("/api/v1/hazards", json=payload)
        data = resp.json()
        assert data["residual_risk"] == "Low"
        assert data["approval_status"] == "Open"


class TestListHazards:
    @patch("services.safety_compliance.hazard_register._query_hazards", return_value=[
        {"hazardId": "HAZ-001", "description": "Test", "approvalStatus": "Open"}
    ])
    def test_list_hazards(self, mock_query, client):
        resp = client.get("/api/v1/hazards")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["hazards"][0]["hazardId"] == "HAZ-001"

    @patch("services.safety_compliance.hazard_register._query_hazards", return_value=[])
    def test_list_hazards_with_subsystem_filter(self, mock_query, client):
        resp = client.get("/api/v1/hazards?subsystem=defect_detector")
        assert resp.status_code == 200
        mock_query.assert_called_once_with("defect_detector")

    @patch("services.safety_compliance.hazard_register._query_hazards", return_value=[])
    def test_list_hazards_empty(self, mock_query, client):
        resp = client.get("/api/v1/hazards")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestFlagForReview:
    def test_flag_review_required(self, client):
        payload = {"subsystem": "cybersecurity", "pattern": "repeated_anomaly"}
        resp = client.post("/api/v1/hazards/review-required", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "HAZARD_REVIEW_REQUIRED"
        assert resp.json()["flagged"] is True
