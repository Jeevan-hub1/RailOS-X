"""Unit tests for services.observability.latency_monitor."""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from services.observability import latency_monitor
from services.observability.latency_monitor import (
    app,
    _process_span,
    _compute_and_record,
    _evict_expired_traces,
    FIRST_SPAN,
    LAST_SPAN,
    SLA_THRESHOLD_MS,
)


@pytest.fixture(autouse=True)
def _reset_trace_store():
    """Reset the in-memory trace stores between tests."""
    latency_monitor._trace_store.clear()
    latency_monitor._trace_alert_type.clear()
    latency_monitor._trace_expiry.clear()
    yield
    latency_monitor._trace_store.clear()
    latency_monitor._trace_alert_type.clear()
    latency_monitor._trace_expiry.clear()


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestMetricsEndpoint:
    def test_metrics_returns_prometheus(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"] or "text/plain" in resp.headers.get("content-type", "")


class TestSpanIngestion:
    def test_ingest_spans_array(self, client):
        spans = [
            {"trace_id": "t1", "span_name": "sensor_ingest_edge", "start_time_unix_nano": 1000000000},
            {"trace_id": "t1", "span_name": "kafka_publish", "start_time_unix_nano": 1100000000},
        ]
        resp = client.post("/spans", json=spans)
        assert resp.status_code == 202
        assert resp.json()["accepted"] == 2

    def test_ingest_spans_object_with_spans_key(self, client):
        body = {"spans": [
            {"trace_id": "t2", "span_name": "sensor_ingest_edge", "start_time_unix_nano": 1000000000},
        ]}
        resp = client.post("/spans", json=body)
        assert resp.status_code == 202
        assert resp.json()["accepted"] == 1

    def test_ingest_invalid_json(self, client):
        resp = client.post(
            "/spans",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 202
        assert resp.json()["accepted"] == 0


class TestProcessSpan:
    def test_ignores_unknown_span_name(self):
        _process_span({"trace_id": "t1", "span_name": "unknown_span", "start_time_unix_nano": 100})
        assert "t1" not in latency_monitor._trace_store

    def test_initialises_trace_record(self):
        _process_span({
            "trace_id": "t2",
            "span_name": "sensor_ingest_edge",
            "start_time_unix_nano": 1000,
            "attributes": {"alert_type": "DEFECT_ALERT"},
        })
        assert "t2" in latency_monitor._trace_store
        assert latency_monitor._trace_alert_type["t2"] == "DEFECT_ALERT"

    def test_records_span_time(self):
        _process_span({"trace_id": "t3", "span_name": "sensor_ingest_edge", "start_time_unix_nano": 5000})
        assert latency_monitor._trace_store["t3"]["sensor_ingest_edge"] == 5000

    def test_empty_trace_id_ignored(self):
        _process_span({"trace_id": "", "span_name": "sensor_ingest_edge", "start_time_unix_nano": 100})
        assert "" not in latency_monitor._trace_store

    @patch("services.observability.latency_monitor._compute_and_record")
    def test_terminal_span_triggers_compute(self, mock_compute):
        _process_span({"trace_id": "t4", "span_name": FIRST_SPAN, "start_time_unix_nano": 1000})
        _process_span({"trace_id": "t4", "span_name": LAST_SPAN, "start_time_unix_nano": 6000})
        mock_compute.assert_called_once_with("t4")


class TestComputeAndRecord:
    def test_within_sla_no_breach(self):
        trace_id = "t-ok"
        latency_monitor._trace_store[trace_id] = {
            FIRST_SPAN: 1_000_000_000,  # 1s in ns
            LAST_SPAN:  2_000_000_000,  # 2s in ns  → 1000ms latency
        }
        latency_monitor._trace_expiry[trace_id] = time.monotonic() + 60
        latency_monitor._trace_alert_type[trace_id] = "DEFECT_ALERT"

        _compute_and_record(trace_id)
        # Trace should be cleaned up
        assert trace_id not in latency_monitor._trace_store

    @patch("services.observability.latency_monitor._get_producer", return_value=None)
    def test_sla_breach_detected(self, mock_producer):
        trace_id = "t-breach"
        latency_ms = SLA_THRESHOLD_MS + 1000  # exceeds SLA
        latency_ns = latency_ms * 1_000_000
        latency_monitor._trace_store[trace_id] = {
            FIRST_SPAN: 1_000_000_000,
            LAST_SPAN:  1_000_000_000 + latency_ns,
        }
        latency_monitor._trace_expiry[trace_id] = time.monotonic() + 60
        latency_monitor._trace_alert_type[trace_id] = "SECURITY_ANOMALY"

        _compute_and_record(trace_id)
        assert trace_id not in latency_monitor._trace_store

    def test_missing_first_span_skips(self):
        trace_id = "t-missing"
        latency_monitor._trace_store[trace_id] = {
            FIRST_SPAN: 0,
            LAST_SPAN:  5_000_000_000,
        }
        latency_monitor._trace_expiry[trace_id] = time.monotonic() + 60
        latency_monitor._trace_alert_type[trace_id] = "unknown"
        _compute_and_record(trace_id)

    @patch("services.observability.latency_monitor._get_producer")
    def test_sla_breach_identifies_slowest_stage(self, mock_get_prod):
        mock_producer = MagicMock()
        mock_get_prod.return_value = mock_producer

        trace_id = "t-slow"
        latency_monitor._trace_store[trace_id] = {
            "sensor_ingest_edge": 1_000_000_000,
            "kafka_publish": 1_100_000_000,
            "flink_process": 1_200_000_000,
            "ml_inference": 5_000_000_000,   # big gap → slowest
            "advisory_emit": 5_100_000_000,
            "kafka_consume_dt": 5_200_000_000,
            "digital_twin_render": 5_300_000_000,
            "websocket_push": 5_400_000_000,
            "browser_render": 7_000_000_000,  # 6000ms total > SLA
        }
        latency_monitor._trace_expiry[trace_id] = time.monotonic() + 60
        latency_monitor._trace_alert_type[trace_id] = "DEFECT_ALERT"

        _compute_and_record(trace_id)
        # Producer should have been called to send breach
        mock_producer.send.assert_called_once()


class TestEvictExpiredTraces:
    def test_expired_traces_removed(self):
        latency_monitor._trace_store["old"] = {}
        latency_monitor._trace_expiry["old"] = time.monotonic() - 10
        latency_monitor._trace_alert_type["old"] = "test"

        _evict_expired_traces()
        assert "old" not in latency_monitor._trace_store
        assert "old" not in latency_monitor._trace_expiry

    def test_active_traces_kept(self):
        latency_monitor._trace_store["fresh"] = {}
        latency_monitor._trace_expiry["fresh"] = time.monotonic() + 100
        latency_monitor._trace_alert_type["fresh"] = "test"

        _evict_expired_traces()
        assert "fresh" in latency_monitor._trace_store
