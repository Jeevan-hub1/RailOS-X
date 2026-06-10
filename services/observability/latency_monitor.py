"""
RailOS E2E Alert Latency Monitor (Tasks 19.5, 19.6)
=====================================================
Tracks end-to-end alert delivery from sensor ingestion to browser render.

Span chain (Design §8):
  sensor_ingest_edge → kafka_publish → flink_process → ml_inference
  → advisory_emit → kafka_consume_dt → digital_twin_render
  → websocket_push → browser_render

Accepts OTel span batches via POST /spans (JSON).
When the terminal span (browser_render) arrives for a trace, computes
total e2e latency and:
  - Logs SLA breach (>5000ms) to audit Kafka topic
  - Records Prometheus histogram observation

Exposes:
  GET /metrics — Prometheus metrics
  POST /spans  — OTel span batch ingestion endpoint

Satisfies: Req 25 (e2e latency ≤5s, p50/p95/p99 metrics), Design §8
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response, status
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

# ── Kafka import (graceful fallback for envs without kafka-python) ─────────────
try:
    from kafka import KafkaProducer
    _KAFKA_AVAILABLE = True
except ImportError:
    _KAFKA_AVAILABLE = False

# ── Configuration ──────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP     = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
SLA_THRESHOLD_MS    = int(os.environ.get("SLA_THRESHOLD_MS", "5000"))
AUDIT_TOPIC         = "audit.inference"
METRICS_PORT        = int(os.environ.get("PORT", "8080"))

# Ordered span names defining the e2e chain (Design §8)
SPAN_CHAIN = [
    "sensor_ingest_edge",
    "kafka_publish",
    "flink_process",
    "ml_inference",
    "advisory_emit",
    "kafka_consume_dt",
    "digital_twin_render",
    "websocket_push",
    "browser_render",
]
FIRST_SPAN = SPAN_CHAIN[0]
LAST_SPAN  = SPAN_CHAIN[-1]

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("latency-monitor")

# ── Prometheus metrics ──────────────────────────────────────────────────────────
e2e_latency_histogram = Histogram(
    "railos_alert_e2e_latency_seconds",
    "End-to-end alert latency from sensor_ingest_edge to browser_render",
    labelnames=["alert_type"],
    buckets=[0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0, float("inf")],
)

sla_breach_counter = Counter(
    "railos_alert_e2e_sla_breaches_total",
    "Number of alert deliveries that exceeded the 5s SLA",
    labelnames=["alert_type"],
)

spans_received_counter = Counter(
    "railos_latency_monitor_spans_received_total",
    "Total span batches received",
)

# ── In-memory trace store: trace_id → {span_name: start_time_ns} ─────────────
# Evicted after 60s to prevent unbounded growth
_trace_store: dict[str, dict[str, int]] = {}
_trace_alert_type: dict[str, str] = {}
_trace_expiry: dict[str, float] = {}
TRACE_TTL_S = 60.0

# ── Kafka producer ──────────────────────────────────────────────────────────────
_producer: Any = None

def _get_producer() -> Any:
    global _producer
    if _producer is None and _KAFKA_AVAILABLE:
        try:
            _producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                acks="all",
                retries=3,
            )
        except Exception as exc:
            log.warning("Kafka producer init failed: %s — SLA breaches will be logged only", exc)
    return _producer

# ── FastAPI app ─────────────────────────────────────────────────────────────────
app = FastAPI(title="RailOS E2E Latency Monitor", docs_url=None, redoc_url=None)


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/spans", status_code=status.HTTP_202_ACCEPTED)
async def ingest_spans(request: Request) -> dict:
    """
    Receive an OTel span batch (JSON array of span objects).
    Each span should have:
      trace_id (str), span_name (str), start_time_unix_nano (int),
      end_time_unix_nano (int), attributes (dict, optional)
    """
    spans_received_counter.inc()
    _evict_expired_traces()

    try:
        body = await request.json()
    except Exception:
        return {"accepted": 0}

    spans: list[dict] = body if isinstance(body, list) else body.get("spans", [])

    for span in spans:
        _process_span(span)

    return {"accepted": len(spans)}


def _process_span(span: dict) -> None:
    trace_id: str = span.get("trace_id", "")
    span_name: str = span.get("span_name", "")
    start_ns: int  = int(span.get("start_time_unix_nano", 0))

    if not trace_id or span_name not in SPAN_CHAIN:
        return

    now = time.monotonic()

    # Initialise trace record
    if trace_id not in _trace_store:
        _trace_store[trace_id] = {}
        _trace_expiry[trace_id] = now + TRACE_TTL_S
        # Extract alert_type from span attributes
        attrs = span.get("attributes", {})
        _trace_alert_type[trace_id] = attrs.get("alert_type", "unknown")

    _trace_store[trace_id][span_name] = start_ns

    # When the terminal span arrives, compute e2e latency
    if span_name == LAST_SPAN and FIRST_SPAN in _trace_store.get(trace_id, {}):
        _compute_and_record(trace_id)


def _compute_and_record(trace_id: str) -> None:
    spans = _trace_store.get(trace_id, {})
    first_ns = spans.get(FIRST_SPAN, 0)
    last_ns  = spans.get(LAST_SPAN, 0)

    if first_ns == 0 or last_ns == 0:
        return

    latency_ms = (last_ns - first_ns) / 1_000_000
    latency_s  = latency_ms / 1000.0
    alert_type = _trace_alert_type.get(trace_id, "unknown")

    # Record histogram observation (p50/p95/p99 computed by Prometheus)
    e2e_latency_histogram.labels(alert_type=alert_type).observe(latency_s)

    if latency_ms > SLA_THRESHOLD_MS:
        # Identify the slowest stage
        ordered_times = [(s, spans[s]) for s in SPAN_CHAIN if s in spans]
        slowest_stage = "unknown"
        max_gap = 0
        for i in range(len(ordered_times) - 1):
            gap = ordered_times[i + 1][1] - ordered_times[i][1]
            if gap > max_gap:
                max_gap = gap
                slowest_stage = ordered_times[i + 1][0]

        breach_record = {
            "alertType": "E2E_LATENCY_SLA_BREACH",
            "traceId": trace_id,
            "alertEventType": alert_type,
            "measuredLatencyMs": round(latency_ms, 1),
            "slaThresholdMs": SLA_THRESHOLD_MS,
            "slowestStage": slowest_stage,
        }

        log.warning("SLA BREACH trace_id=%s latency_ms=%.1f stage=%s",
                    trace_id, latency_ms, slowest_stage)

        sla_breach_counter.labels(alert_type=alert_type).inc()

        # Publish breach to audit Kafka topic
        producer = _get_producer()
        if producer:
            try:
                producer.send(AUDIT_TOPIC, value=json.dumps(breach_record).encode())
                producer.flush(timeout=3)
            except Exception as exc:
                log.error("Failed to publish SLA breach to Kafka: %s", exc)

    # Clean up resolved trace
    _trace_store.pop(trace_id, None)
    _trace_expiry.pop(trace_id, None)
    _trace_alert_type.pop(trace_id, None)


def _evict_expired_traces() -> None:
    now = time.monotonic()
    expired = [tid for tid, exp in _trace_expiry.items() if now > exp]
    for tid in expired:
        _trace_store.pop(tid, None)
        _trace_expiry.pop(tid, None)
        _trace_alert_type.pop(tid, None)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=METRICS_PORT, log_config=None)
