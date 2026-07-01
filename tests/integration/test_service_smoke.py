"""
Integration smoke tests — exercise each service's REAL FastAPI app end-to-end
through Starlette's TestClient, with no external infrastructure required.

These complement the unit/property tests: they verify the HTTP layer, routing,
serialization, and in-memory business logic actually wire together.

Marked ``integration`` (registered in pyproject.toml). Endpoints that require
Kafka/PostgreSQL (e.g. the gate authorize/enqueue flow, advisory publish) are
intentionally not exercised here — those belong to the infra-backed CI job.

NOTE: we construct ``TestClient(app)`` WITHOUT the context-manager form on
purpose. The context manager fires FastAPI startup events, which would start
Prometheus metrics servers and background simulation loops; plain construction
skips lifespan, keeping these tests hermetic.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_kavach_health():
    from services.kavach_advisory.kavach_advisory import app

    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_digital_twin_state_and_corridor():
    from services.digital_twin.backend.websocket_server import app

    c = TestClient(app)
    assert c.get("/health").status_code == 200

    state = c.get("/api/v1/state").json()
    assert "trains" in state and "stats" in state
    assert len(state["trains"]) >= 1
    # Each train carries a position on the corridor.
    assert all("km" in t for t in state["trains"])

    corridor = c.get("/api/v1/corridor").json()
    assert corridor["totalKm"] == 72
    assert any(s["id"] == "NDLS" for s in corridor["stations"])


def test_marl_health_and_reads():
    from services.marl_scheduler.service.scheduler_service import app

    c = TestClient(app)
    assert c.get("/health").status_code == 200
    # In-memory read endpoints (no Kafka).
    assert c.get("/api/v1/scheduler/corridor").status_code == 200
    assert c.get("/api/v1/scheduler/history").status_code == 200


def test_authgate_health():
    from services.authorization_gate.gate_service import app

    assert TestClient(app).get("/health").status_code == 200
