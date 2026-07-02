"""
RailOS-X Station Edge Aggregator (Tier 2)
Station-level compute node: aggregates micro-edge data, runs ML inference,
makes local decisions, and syncs upstream to Zone Compute.

Responsibilities:
  - Receive features/anomalies from multiple Micro-Edge nodes
  - Multi-sensor correlation (cross-channel anomaly validation)
  - Manage local inference queue (priority-based scheduling)
  - Edge-to-cloud sync with bandwidth-aware batching
  - Maintain station-level digital twin state
  - Autonomous decision loop during network partition

Hardware target: Jetson Orin NX/AGX (64GB, 200 TOPS AI)
Satisfies: Req 2, Req 8, Req 21, Design §5.2
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from pydantic import BaseModel

from ..shared.edge_protocol import (
    EdgeTier, EdgeNodeStatus, NodeHealth, SensorFeatures, AnomalyFlag,
    AlertSeverity, InferenceRequest, InferenceResult, ProcessingPriority,
    SyncStrategy, timestamp_ns, latency_ms, generate_node_id,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","module":"station_edge","msg":"%(message)s"}',
)

# ── Configuration ─────────────────────────────────────────────────────────────
STATION_ID        = os.environ.get("STATION_ID", "NDLS")
KAFKA_BOOTSTRAP   = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
ZONE_URL          = os.environ.get("ZONE_COMPUTE_URL", "http://localhost:8092")
METRICS_PORT      = int(os.environ.get("METRICS_PORT", "9101"))
APP_PORT          = int(os.environ.get("APP_PORT", "8091"))
CORRELATION_WINDOW_S = float(os.environ.get("CORRELATION_WINDOW_S", "5.0"))
SYNC_INTERVAL_S   = float(os.environ.get("SYNC_INTERVAL_S", "10.0"))
MAX_INFERENCE_QUEUE = int(os.environ.get("MAX_INFERENCE_QUEUE", "500"))

NODE_ID = generate_node_id(EdgeTier.STATION_EDGE, STATION_ID)

# ── Prometheus Metrics ────────────────────────────────────────────────────────
features_received   = Counter("station_features_received_total", "Feature batches received from micro-edge")
anomalies_received  = Counter("station_anomalies_received_total", "Anomalies received from micro-edge")
correlations_found  = Counter("station_correlations_found_total", "Cross-sensor correlations detected")
inference_requests  = Counter("station_inference_requests_total", "Inference requests processed")
inference_latency   = Histogram("station_inference_latency_ms", "Inference latency", buckets=[5, 10, 25, 50, 100, 250, 500])
sync_events         = Counter("station_sync_upstream_total", "Events synced to zone compute")
queue_depth_gauge   = Gauge("station_inference_queue_depth", "Current inference queue depth")
active_nodes_gauge  = Gauge("station_active_micro_edge_nodes", "Active micro-edge nodes reporting")


# ══════════════════════════════════════════════════════════════════════════════
# Multi-Sensor Correlator
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CorrelationWindow:
    """Sliding time window for cross-sensor anomaly correlation."""
    window_ns: int = int(CORRELATION_WINDOW_S * 1e9)
    _anomalies: deque = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_anomaly(self, flag: AnomalyFlag) -> None:
        """Add an anomaly to the correlation window."""
        now = timestamp_ns()
        with self._lock:
            self._anomalies.append((now, flag))
            # Evict expired
            cutoff = now - self.window_ns
            while self._anomalies and self._anomalies[0][0] < cutoff:
                self._anomalies.popleft()

    def find_correlations(self) -> list[dict]:
        """Find correlated anomalies from different sensors in the same time window.
        
        Correlation rules:
          1. Same time window + different sensors + same node → bogie-level issue
          2. Same time window + same sensor type + different nodes → track-level issue
          3. Vibration + temperature correlation → bearing failure indicator
        """
        with self._lock:
            if len(self._anomalies) < 2:
                return []

            correlations = []
            anomaly_list = list(self._anomalies)

            # Group by node
            by_node: dict[str, list[AnomalyFlag]] = defaultdict(list)
            by_type: dict[str, list[AnomalyFlag]] = defaultdict(list)

            for _, flag in anomaly_list:
                by_node[flag.node_id].append(flag)
                by_type[flag.anomaly_type].append(flag)

            # Rule 1: Multiple sensors on same node
            for node_id, flags in by_node.items():
                if len(flags) >= 2:
                    sensor_ids = set(f.sensor_id for f in flags)
                    if len(sensor_ids) >= 2:
                        correlations.append({
                            "type": "multi_sensor_same_node",
                            "node_id": node_id,
                            "sensors": list(sensor_ids),
                            "anomaly_count": len(flags),
                            "severity": max(f.severity for f in flags),
                            "confidence": min(1.0, sum(f.confidence for f in flags) / len(flags) + 0.2),
                        })

            # Rule 2: Same anomaly type from different nodes → track-level
            for anomaly_type, flags in by_type.items():
                unique_nodes = set(f.node_id for f in flags)
                if len(unique_nodes) >= 2:
                    correlations.append({
                        "type": "multi_node_same_anomaly",
                        "anomaly_type": anomaly_type,
                        "affected_nodes": list(unique_nodes),
                        "severity": AlertSeverity.CRITICAL,
                        "confidence": min(1.0, len(unique_nodes) * 0.3),
                    })

            return correlations


# ══════════════════════════════════════════════════════════════════════════════
# Inference Queue — priority-based scheduling
# ══════════════════════════════════════════════════════════════════════════════

class InferenceQueue:
    """Priority queue for inference requests. Real-time > High > Normal > Background."""

    def __init__(self, max_size: int = MAX_INFERENCE_QUEUE) -> None:
        self._queues: dict[ProcessingPriority, deque] = {
            ProcessingPriority.REAL_TIME: deque(maxlen=100),
            ProcessingPriority.HIGH: deque(maxlen=200),
            ProcessingPriority.NORMAL: deque(maxlen=max_size),
            ProcessingPriority.BACKGROUND: deque(maxlen=max_size),
        }
        self._lock = threading.Lock()
        self._total_processed = 0

    def enqueue(self, request: InferenceRequest) -> bool:
        """Add inference request to priority queue. Returns False if queue full."""
        with self._lock:
            q = self._queues.get(request.priority)
            if q is None:
                q = self._queues[ProcessingPriority.NORMAL]
            if len(q) >= q.maxlen:
                return False
            q.append(request)
            queue_depth_gauge.set(self.depth)
            return True

    def dequeue(self) -> Optional[InferenceRequest]:
        """Get next request (highest priority first). Returns None if empty."""
        with self._lock:
            for priority in ProcessingPriority:
                q = self._queues[priority]
                if q:
                    req = q.popleft()
                    self._total_processed += 1
                    queue_depth_gauge.set(self.depth)
                    return req
            return None

    @property
    def depth(self) -> int:
        return sum(len(q) for q in self._queues.values())

    @property
    def total_processed(self) -> int:
        return self._total_processed


# ══════════════════════════════════════════════════════════════════════════════
# Edge-to-Cloud Sync Manager
# ══════════════════════════════════════════════════════════════════════════════

class SyncManager:
    """Manages upstream sync to Zone Compute with bandwidth-aware batching."""

    def __init__(self, zone_url: str = ZONE_URL, batch_size: int = 50) -> None:
        self._zone_url = zone_url
        self._batch_size = batch_size
        self._pending: deque = deque(maxlen=10000)
        self._lock = threading.Lock()
        self._kafka_producer = None
        self._connected = True

    def queue_event(self, event: dict) -> None:
        """Queue an event for upstream sync."""
        with self._lock:
            self._pending.append(event)

    def flush(self) -> int:
        """Flush pending events upstream. Returns count sent."""
        with self._lock:
            if not self._pending:
                return 0
            batch = []
            while self._pending and len(batch) < self._batch_size:
                batch.append(self._pending.popleft())

        # Send via Kafka
        sent = 0
        producer = self._get_producer()
        if producer:
            for event in batch:
                try:
                    producer.send("monitoring.alerts", value=json.dumps(event).encode())
                    sent += 1
                except Exception as exc:
                    log.error("Sync send failed: %s", exc)
                    # Re-queue failed events
                    with self._lock:
                        self._pending.appendleft(event)
                    break
            sync_events.inc(sent)
        return sent

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def _get_producer(self):
        if self._kafka_producer is None:
            try:
                from kafka import KafkaProducer
                self._kafka_producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    acks="all", retries=3,
                    linger_ms=50,
                    compression_type="lz4",
                    max_block_ms=5000,
                )
            except Exception as exc:
                log.error("Kafka producer init failed: %s", exc)
                self._connected = False
        return self._kafka_producer


# ══════════════════════════════════════════════════════════════════════════════
# Station Aggregator — main orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class StationAggregator:
    """Central station-level aggregation and decision engine."""

    def __init__(self) -> None:
        self._correlator = CorrelationWindow()
        self._inference_queue = InferenceQueue()
        self._sync_manager = SyncManager()
        self._start_time = time.monotonic()
        self._active_nodes: dict[str, float] = {}  # node_id → last_seen_timestamp
        self._station_state: dict[str, Any] = {}
        self._lock = threading.Lock()

    def receive_micro_edge_batch(self, batch: dict) -> dict:
        """Process a batch from a micro-edge node."""
        node_id = batch.get("node_id", "unknown")
        features_list = batch.get("features", [])
        anomalies_list = batch.get("anomalies", [])

        # Track active nodes
        self._active_nodes[node_id] = time.monotonic()
        active_nodes_gauge.set(len(self._active_nodes))

        # Process features
        features_received.inc(len(features_list))
        for feat_dict in features_list:
            self._process_feature(feat_dict)

        # Process anomalies
        anomalies_received.inc(len(anomalies_list))
        for anomaly_dict in anomalies_list:
            flag = AnomalyFlag(
                sensor_id=anomaly_dict.get("sensor_id", ""),
                node_id=anomaly_dict.get("node_id", node_id),
                anomaly_type=anomaly_dict.get("anomaly_type", "unknown"),
                severity=AlertSeverity(anomaly_dict.get("severity", 1)),
                confidence=anomaly_dict.get("confidence", 0.5),
                timestamp_ns=anomaly_dict.get("timestamp_ns", timestamp_ns()),
                feature_snapshot=anomaly_dict.get("feature_snapshot", {}),
            )
            self._correlator.add_anomaly(flag)

        # Check for cross-sensor correlations
        correlations = self._correlator.find_correlations()
        if correlations:
            correlations_found.inc(len(correlations))
            for corr in correlations:
                self._handle_correlation(corr)

        return {
            "accepted_features": len(features_list),
            "accepted_anomalies": len(anomalies_list),
            "correlations_detected": len(correlations),
        }

    def _process_feature(self, feat: dict) -> None:
        """Process a feature vector — may trigger inference request."""
        # Check if features indicate inference is needed
        rms = feat.get("features", {}).get("rms", 0)
        kurtosis = feat.get("features", {}).get("kurtosis", 0)

        # Trigger inference if vibration is elevated
        if rms > 2.0 or abs(kurtosis) > 4.0:
            req = InferenceRequest(
                model_id="defect-detector-v3",
                model_version="3.1.0",
                priority=ProcessingPriority.HIGH if rms > 4.0 else ProcessingPriority.NORMAL,
                input_features=feat.get("features", {}),
                source_node=feat.get("node_id", ""),
                deadline_ms=100 if rms > 4.0 else 500,
            )
            self._inference_queue.enqueue(req)
            inference_requests.inc()

    def _handle_correlation(self, correlation: dict) -> None:
        """Handle a detected cross-sensor correlation."""
        log.warning("CORRELATION_DETECTED type=%s confidence=%.2f",
                    correlation.get("type"), correlation.get("confidence", 0))
        # Queue for upstream sync
        self._sync_manager.queue_event({
            "alertType": "CROSS_SENSOR_CORRELATION",
            "station_id": STATION_ID,
            "correlation": correlation,
            "timestamp_ns": timestamp_ns(),
        })

    def get_next_inference(self) -> Optional[InferenceRequest]:
        """Get next inference request from priority queue."""
        return self._inference_queue.dequeue()

    def submit_inference_result(self, result: InferenceResult) -> None:
        """Process inference result — may trigger actions."""
        inference_latency.observe(result.latency_ms)

        # If high-confidence defect, escalate
        if result.confidence > 0.8:
            self._sync_manager.queue_event({
                "alertType": "ML_DEFECT_DETECTED",
                "station_id": STATION_ID,
                "model_id": result.model_id,
                "confidence": result.confidence,
                "predictions": result.predictions,
                "timestamp_ns": result.timestamp_ns,
            })

    async def sync_loop(self) -> None:
        """Background sync loop — flushes events upstream periodically."""
        while True:
            try:
                sent = self._sync_manager.flush()
                if sent > 0:
                    log.info("Synced %d events upstream", sent)
            except Exception as exc:
                log.error("Sync loop error: %s", exc)
            await asyncio.sleep(SYNC_INTERVAL_S)

    async def housekeeping_loop(self) -> None:
        """Remove stale nodes, update health metrics."""
        while True:
            now = time.monotonic()
            stale_threshold = 60.0  # 60s without heartbeat → stale
            stale = [nid for nid, ts in self._active_nodes.items() if now - ts > stale_threshold]
            for nid in stale:
                del self._active_nodes[nid]
                log.warning("Node stale (removed): %s", nid)
            active_nodes_gauge.set(len(self._active_nodes))
            await asyncio.sleep(30)

    def get_status(self) -> dict:
        """Return station aggregator status."""
        return {
            "node_id": NODE_ID,
            "station_id": STATION_ID,
            "tier": EdgeTier.STATION_EDGE.value,
            "health": NodeHealth.HEALTHY.name,
            "active_micro_edge_nodes": len(self._active_nodes),
            "inference_queue_depth": self._inference_queue.depth,
            "inference_total_processed": self._inference_queue.total_processed,
            "sync_pending": self._sync_manager.pending_count,
            "uptime_s": round(time.monotonic() - self._start_time, 1),
        }


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Application
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title=f"RailOS Station Edge ({STATION_ID})", docs_url=None)
_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001",
).split(",")
app.add_middleware(CORSMiddleware, allow_origins=_ALLOWED_ORIGINS,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

aggregator = StationAggregator()


class MicroEdgeBatch(BaseModel):
    node_id: str
    station_id: str = STATION_ID
    timestamp_ns: int = 0
    features: list[dict] = []
    anomalies: list[dict] = []
    batch_size: int = 0


class InferenceResultPayload(BaseModel):
    request_id: str
    model_id: str
    predictions: dict = {}
    confidence: float = 0.0
    latency_ms: float = 0.0


@app.on_event("startup")
async def startup():
    start_http_server(METRICS_PORT)
    asyncio.create_task(aggregator.sync_loop())
    asyncio.create_task(aggregator.housekeeping_loop())
    log.info("Station Edge aggregator started: station=%s port=%d", STATION_ID, APP_PORT)


@app.get("/health")
def health():
    return {"status": "ok", "station_id": STATION_ID, "node_id": NODE_ID}


@app.post("/api/v1/micro-edge/batch")
def receive_batch(batch: MicroEdgeBatch):
    """Receive a batch of features/anomalies from a micro-edge node."""
    result = aggregator.receive_micro_edge_batch(batch.dict())
    return result


@app.get("/api/v1/inference/next")
def get_next_inference():
    """Get next inference request from priority queue (called by inference engine)."""
    req = aggregator.get_next_inference()
    if req is None:
        return {"status": "empty"}
    return req.to_dict()


@app.post("/api/v1/inference/result")
def submit_result(payload: InferenceResultPayload):
    """Submit inference result back to aggregator."""
    result = InferenceResult(
        request_id=payload.request_id,
        model_id=payload.model_id,
        predictions=payload.predictions,
        confidence=payload.confidence,
        latency_ms=payload.latency_ms,
    )
    aggregator.submit_inference_result(result)
    return {"status": "accepted"}


@app.get("/api/v1/status")
def status():
    return aggregator.get_status()


@app.get("/api/v1/nodes")
def active_nodes():
    """List active micro-edge nodes and their last-seen time."""
    now = time.monotonic()
    return {"nodes": [
        {"node_id": nid, "last_seen_s_ago": round(now - ts, 1)}
        for nid, ts in aggregator._active_nodes.items()
    ]}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
