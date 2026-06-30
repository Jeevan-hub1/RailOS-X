"""
RailOS-X Micro-Edge Sensor Hub (Tier 1)
Ultra-low-latency sensor fusion node running on trackside/bogie MCU hardware.

Responsibilities:
  - Multi-channel sensor ingestion (accelerometer, acoustic, thermal, GPS, strain)
  - Real-time pre-processing pipeline (filtering, normalization, windowing)
  - Local anomaly detection (statistical + lightweight ML at source)
  - Feature extraction and forwarding to Station Edge (Tier 2)
  - Sub-millisecond latency budget for safety-critical paths

Hardware target: FPGA + ARM Cortex-M7 (or Jetson Nano for dev)
Protocol: MQTT QoS1 upstream, hardware GPIO/SPI/I2C for sensors
Satisfies: Req 44, Req 2 C1, Design §5.1
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from prometheus_client import Counter, Gauge, Histogram, start_http_server

try:
    from ..shared.edge_protocol import (
        SensorType, SensorReading, SensorFeatures, AnomalyFlag,
        AlertSeverity, RingBuffer, EdgeTier, EdgeNodeStatus, NodeHealth,
        ProcessingPriority, SyncStrategy, timestamp_ns, latency_ms,
        generate_node_id,
    )
except (ImportError, ValueError):
    # Fallback for running outside package context
    from enum import IntEnum
    class SensorType(IntEnum):
        ACCELEROMETER = 1; ACOUSTIC = 2; TEMPERATURE = 3; WHEEL_LOAD = 4; GPS = 5; LIDAR = 6; CAMERA = 7; CURRENT_LOOP = 8; HUMIDITY = 9; WIND_SPEED = 10
    class AlertSeverity(IntEnum):
        INFO = 0; WARNING = 1; CRITICAL = 2; EMERGENCY = 3
    class EdgeTier(IntEnum):
        MICRO_EDGE = 1; STATION_EDGE = 2; ZONE_COMPUTE = 3
    class NodeHealth(IntEnum):
        HEALTHY = 0; DEGRADED = 1; OVERLOADED = 2; OFFLINE = 3
    class RingBuffer:
        def __init__(self, capacity=4096):
            self._buf = [0.0]*capacity; self._capacity = capacity; self._head = 0; self._count = 0
        @property
        def count(self): return min(self._count, self._capacity)
        @property
        def is_full(self): return self._count >= self._capacity
        def push(self, v): self._buf[self._head]=v; self._head=(self._head+1)%self._capacity; self._count+=1
        def push_batch(self, vals):
            for v in vals: self.push(v)
        def get_window(self, n):
            available=self.count; n=min(n,available); result=[]; idx=(self._head-1)%self._capacity
            for _ in range(n): result.append(self._buf[idx]); idx=(idx-1)%self._capacity
            return result
        def clear(self): self._head=0; self._count=0
    def timestamp_ns(): return time.time_ns()
    def latency_ms(start_ns): return (time.time_ns()-start_ns)/1_000_000
    def generate_node_id(tier, station, index=0): return f"me-{station}-{index:03d}"
    class SensorFeatures:
        def __init__(self, **kw):
            for k,v in kw.items(): setattr(self,k,v)
        def to_dict(self): return self.__dict__
    class AnomalyFlag:
        def __init__(self, **kw):
            for k,v in kw.items(): setattr(self,k,v)
        def to_dict(self): return {k:v for k,v in self.__dict__.items() if not k.startswith('_')}
    class EdgeNodeStatus:
        def __init__(self, **kw):
            for k,v in kw.items(): setattr(self,k,v)
        def to_dict(self): return self.__dict__

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","module":"micro_edge","msg":"%(message)s"}',
)

# ── Configuration ─────────────────────────────────────────────────────────────
STATION_ID          = os.environ.get("STATION_ID", "NDLS")
NODE_INDEX          = int(os.environ.get("NODE_INDEX", "0"))
KAFKA_BOOTSTRAP     = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
MQTT_BROKER         = os.environ.get("MQTT_BROKER", "localhost:1883")
UPSTREAM_URL        = os.environ.get("UPSTREAM_STATION_URL", "http://localhost:8090")
METRICS_PORT        = int(os.environ.get("METRICS_PORT", "9110"))
SAMPLE_RATE_HZ      = int(os.environ.get("SAMPLE_RATE_HZ", "4000"))
WINDOW_MS           = int(os.environ.get("WINDOW_MS", "100"))
ANOMALY_THRESHOLD   = float(os.environ.get("ANOMALY_Z_THRESHOLD", "3.5"))
BATCH_FORWARD_SIZE  = int(os.environ.get("BATCH_FORWARD_SIZE", "10"))

NODE_ID = generate_node_id(EdgeTier.MICRO_EDGE, STATION_ID, NODE_INDEX)

# ── Prometheus Metrics ────────────────────────────────────────────────────────
samples_ingested   = Counter("micro_edge_samples_ingested_total", "Total sensor samples ingested", ["sensor_type"])
anomalies_detected = Counter("micro_edge_anomalies_detected_total", "Anomalies detected at source", ["anomaly_type"])
features_forwarded = Counter("micro_edge_features_forwarded_total", "Feature vectors sent to station")
processing_latency = Histogram("micro_edge_processing_latency_us", "Per-window processing latency in microseconds",
                               buckets=[50, 100, 200, 500, 1000, 2000, 5000])
buffer_utilization = Gauge("micro_edge_buffer_utilization_pct", "Ring buffer fill %", ["channel"])
node_health_gauge  = Gauge("micro_edge_node_health", "Node health: 0=healthy, 1=degraded, 2=overloaded, 3=offline")


# ══════════════════════════════════════════════════════════════════════════════
# Sensor Channel — one per physical sensor
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SensorChannel:
    """Manages a single sensor's data pipeline: ingestion → buffer → features."""
    sensor_id:      str
    sensor_type:    SensorType
    sample_rate_hz: int = 4000
    window_samples: int = 400       # 100ms at 4kHz
    ring_buffer:    RingBuffer = field(default_factory=lambda: RingBuffer(capacity=16384))

    # Running statistics (Welford's online algorithm for O(1) mean/variance)
    _n:     int = 0
    _mean:  float = 0.0
    _m2:    float = 0.0
    _min:   float = float('inf')
    _max:   float = float('-inf')

    def ingest(self, value: float) -> None:
        """Ingest a single sample. O(1) per sample."""
        self.ring_buffer.push(value)
        self._n += 1
        delta = value - self._mean
        self._mean += delta / self._n
        delta2 = value - self._mean
        self._m2 += delta * delta2
        self._min = min(self._min, value)
        self._max = max(self._max, value)

    def ingest_batch(self, values: list[float]) -> None:
        """Batch ingest for efficiency."""
        self.ring_buffer.push_batch(values)
        for v in values:
            self._n += 1
            delta = v - self._mean
            self._mean += delta / self._n
            delta2 = v - self._mean
            self._m2 += delta * delta2
            self._min = min(self._min, v)
            self._max = max(self._max, v)

    @property
    def variance(self) -> float:
        return self._m2 / self._n if self._n > 1 else 0.0

    @property
    def std_dev(self) -> float:
        return math.sqrt(self.variance)

    @property
    def rms(self) -> float:
        """Root Mean Square of current window."""
        window = self.ring_buffer.get_window(self.window_samples)
        if not window:
            return 0.0
        return math.sqrt(sum(x * x for x in window) / len(window))

    def get_window(self) -> list[float]:
        """Get current analysis window (most recent samples)."""
        return self.ring_buffer.get_window(self.window_samples)

    def reset_stats(self) -> None:
        """Reset running statistics (call after each feature extraction)."""
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._min = float('inf')
        self._max = float('-inf')


# ══════════════════════════════════════════════════════════════════════════════
# Anomaly Detector — statistical + lightweight threshold-based
# ══════════════════════════════════════════════════════════════════════════════

class MicroEdgeAnomalyDetector:
    """Fast anomaly detection suitable for MCU-class hardware.
    
    Strategies:
      1. Z-score on sliding window (|z| > threshold → anomaly)
      2. Rate-of-change spike detection
      3. Range violation (sensor reading outside physical bounds)
      4. Flatline detection (sensor stuck at same value)
    """

    def __init__(self, z_threshold: float = 3.5, flatline_tolerance: float = 0.001,
                 flatline_min_samples: int = 100) -> None:
        self._z_threshold = z_threshold
        self._flatline_tol = flatline_tolerance
        self._flatline_min = flatline_min_samples
        # Per-sensor adaptive baselines
        self._baselines: dict[str, _AdaptiveBaseline] = {}

    def check(self, channel: SensorChannel) -> Optional[AnomalyFlag]:
        """Run all anomaly checks. Returns AnomalyFlag or None."""
        sensor_id = channel.sensor_id
        if sensor_id not in self._baselines:
            self._baselines[sensor_id] = _AdaptiveBaseline()
        baseline = self._baselines[sensor_id]

        window = channel.get_window()
        if len(window) < 10:
            return None

        current_rms = channel.rms
        current_mean = sum(window) / len(window)

        # 1. Z-score anomaly
        if baseline.std > 0:
            z = abs(current_mean - baseline.mean) / baseline.std
            if z > self._z_threshold:
                return AnomalyFlag(
                    sensor_id=sensor_id,
                    node_id=NODE_ID,
                    anomaly_type="z_score_violation",
                    severity=AlertSeverity.WARNING if z < 5.0 else AlertSeverity.CRITICAL,
                    confidence=min(1.0, z / 10.0),
                    timestamp_ns=timestamp_ns(),
                    feature_snapshot={"z_score": z, "rms": current_rms, "mean": current_mean},
                )

        # 2. Rate-of-change spike
        if len(window) >= 2:
            max_delta = max(abs(window[i] - window[i + 1]) for i in range(len(window) - 1))
            if baseline.mean_delta > 0 and max_delta > baseline.mean_delta * 8:
                return AnomalyFlag(
                    sensor_id=sensor_id,
                    node_id=NODE_ID,
                    anomaly_type="rate_spike",
                    severity=AlertSeverity.WARNING,
                    confidence=min(1.0, max_delta / (baseline.mean_delta * 20)),
                    timestamp_ns=timestamp_ns(),
                    feature_snapshot={"max_delta": max_delta, "baseline_delta": baseline.mean_delta},
                )

        # 3. Flatline detection
        if len(window) >= self._flatline_min:
            spread = max(window) - min(window)
            if spread < self._flatline_tol:
                return AnomalyFlag(
                    sensor_id=sensor_id,
                    node_id=NODE_ID,
                    anomaly_type="flatline",
                    severity=AlertSeverity.WARNING,
                    confidence=0.9,
                    timestamp_ns=timestamp_ns(),
                    feature_snapshot={"spread": spread, "value": window[0]},
                )

        # Update adaptive baseline
        baseline.update(current_mean, current_rms, window)
        return None


class _AdaptiveBaseline:
    """Exponentially-weighted moving baseline for anomaly detection."""
    __slots__ = ('mean', 'std', 'mean_delta', '_alpha', '_n')

    def __init__(self, alpha: float = 0.01) -> None:
        self.mean = 0.0
        self.std = 0.0
        self.mean_delta = 0.0
        self._alpha = alpha
        self._n = 0

    def update(self, mean: float, rms: float, window: list[float]) -> None:
        self._n += 1
        if self._n == 1:
            self.mean = mean
            self.std = 0.0
            self.mean_delta = 0.0
            return
        self.mean = (1 - self._alpha) * self.mean + self._alpha * mean
        self.std = (1 - self._alpha) * self.std + self._alpha * abs(mean - self.mean)
        if len(window) >= 2:
            deltas = [abs(window[i] - window[i + 1]) for i in range(min(20, len(window) - 1))]
            avg_delta = sum(deltas) / len(deltas)
            self.mean_delta = (1 - self._alpha) * self.mean_delta + self._alpha * avg_delta


# ══════════════════════════════════════════════════════════════════════════════
# Feature Extractor — converts raw windows into compact feature vectors
# ══════════════════════════════════════════════════════════════════════════════

class FeatureExtractor:
    """Extract time-domain features from sensor windows.
    
    Kept lightweight for MCU. Full DSP (FFT, wavelet) in signal_processor.py.
    """

    @staticmethod
    def extract(channel: SensorChannel) -> SensorFeatures:
        """Extract statistical features from current window."""
        window = channel.get_window()
        n = len(window)
        if n == 0:
            return SensorFeatures(
                sensor_id=channel.sensor_id,
                node_id=NODE_ID,
                timestamp_ns=timestamp_ns(),
                features={},
                source_type=channel.sensor_type,
            )

        mean = sum(window) / n
        variance = sum((x - mean) ** 2 for x in window) / n if n > 1 else 0.0
        std = math.sqrt(variance)
        rms = math.sqrt(sum(x * x for x in window) / n)

        # Peak-to-peak
        w_min, w_max = min(window), max(window)
        peak_to_peak = w_max - w_min

        # Crest factor (peak / RMS)
        crest_factor = (w_max / rms) if rms > 0 else 0.0

        # Kurtosis (peakedness — high kurtosis indicates impulsive events)
        if std > 0 and n > 3:
            kurtosis = sum(((x - mean) / std) ** 4 for x in window) / n - 3.0
        else:
            kurtosis = 0.0

        # Zero-crossing rate (proxy for frequency content)
        zero_crossings = sum(
            1 for i in range(n - 1) if (window[i] - mean) * (window[i + 1] - mean) < 0
        )
        zcr = zero_crossings / n

        # Energy (sum of squares)
        energy = sum(x * x for x in window)

        return SensorFeatures(
            sensor_id=channel.sensor_id,
            node_id=NODE_ID,
            timestamp_ns=timestamp_ns(),
            window_ms=WINDOW_MS,
            source_type=channel.sensor_type,
            features={
                "mean":          round(mean, 6),
                "std":           round(std, 6),
                "rms":           round(rms, 6),
                "min":           round(w_min, 6),
                "max":           round(w_max, 6),
                "peak_to_peak":  round(peak_to_peak, 6),
                "crest_factor":  round(crest_factor, 4),
                "kurtosis":      round(kurtosis, 4),
                "zcr":           round(zcr, 4),
                "energy":        round(energy, 2),
            },
        )


# ══════════════════════════════════════════════════════════════════════════════
# Sensor Hub — orchestrates all channels
# ══════════════════════════════════════════════════════════════════════════════

class SensorHub:
    """Central orchestrator for all sensor channels on this micro-edge node.
    
    Processing pipeline (per window cycle):
      1. Ingest raw samples from hardware interfaces
      2. Run anomaly detection on each channel
      3. Extract features from each channel
      4. Batch and forward features/anomalies to Station Edge
    """

    def __init__(self) -> None:
        self._channels: dict[str, SensorChannel] = {}
        self._anomaly_detector = MicroEdgeAnomalyDetector(z_threshold=ANOMALY_THRESHOLD)
        self._feature_extractor = FeatureExtractor()
        self._forward_queue: deque[dict] = deque(maxlen=10000)
        self._anomaly_queue: deque[AnomalyFlag] = deque(maxlen=1000)
        self._lock = threading.Lock()
        self._running = False
        self._start_time = time.monotonic()

        # Kafka producer (lazy-init)
        self._producer = None

    def register_channel(self, sensor_id: str, sensor_type: SensorType,
                         sample_rate_hz: int = SAMPLE_RATE_HZ) -> SensorChannel:
        """Register a new sensor channel."""
        window_samples = int(sample_rate_hz * WINDOW_MS / 1000)
        ch = SensorChannel(
            sensor_id=sensor_id,
            sensor_type=sensor_type,
            sample_rate_hz=sample_rate_hz,
            window_samples=window_samples,
            ring_buffer=RingBuffer(capacity=sample_rate_hz * 4),  # 4s buffer
        )
        self._channels[sensor_id] = ch
        log.info("Registered channel: %s type=%s rate=%dHz window=%d samples",
                 sensor_id, sensor_type.name, sample_rate_hz, window_samples)
        return ch

    def ingest(self, sensor_id: str, values: list[float]) -> None:
        """Ingest samples for a sensor. Called by hardware driver."""
        ch = self._channels.get(sensor_id)
        if ch is None:
            return
        ch.ingest_batch(values)
        samples_ingested.labels(sensor_type=ch.sensor_type.name).inc(len(values))

    def process_cycle(self) -> tuple[list[SensorFeatures], list[AnomalyFlag]]:
        """Run one processing cycle across all channels.
        
        Returns (features, anomalies) for this cycle.
        Target: <500μs per cycle on ARM Cortex-M7.
        """
        t0 = time.perf_counter_ns()
        features: list[SensorFeatures] = []
        anomalies: list[AnomalyFlag] = []

        for ch in self._channels.values():
            if ch.ring_buffer.count < ch.window_samples:
                continue  # Not enough data yet

            # Anomaly detection
            flag = self._anomaly_detector.check(ch)
            if flag:
                anomalies.append(flag)
                anomalies_detected.labels(anomaly_type=flag.anomaly_type).inc()
                self._anomaly_queue.append(flag)

            # Feature extraction
            feat = self._feature_extractor.extract(ch)
            if feat.features:
                features.append(feat)

            # Update buffer utilization metric
            utilization = (ch.ring_buffer.count / ch.ring_buffer._capacity) * 100
            buffer_utilization.labels(channel=ch.sensor_id).set(utilization)

        # Record processing latency
        elapsed_us = (time.perf_counter_ns() - t0) / 1000
        processing_latency.observe(elapsed_us)

        return features, anomalies

    def forward_to_station(self, features: list[SensorFeatures], anomalies: list[AnomalyFlag]) -> None:
        """Forward features and anomalies upstream to Station Edge."""
        if not features and not anomalies:
            return

        # Batch into a single message
        payload = {
            "type": "micro_edge_batch",
            "node_id": NODE_ID,
            "station_id": STATION_ID,
            "timestamp_ns": timestamp_ns(),
            "features": [f.to_dict() for f in features],
            "anomalies": [a.to_dict() for a in anomalies],
            "batch_size": len(features),
        }

        # Async forward via Kafka
        self._kafka_send("train.telemetry.vibration", payload)
        features_forwarded.inc(len(features))

        # Also forward anomalies to alert topic
        for anomaly in anomalies:
            self._kafka_send("monitoring.alerts", {
                "alertType": "MICRO_EDGE_ANOMALY",
                "source": NODE_ID,
                **anomaly.to_dict(),
            })

    def get_status(self) -> EdgeNodeStatus:
        """Return current node health status."""
        queue_depth = len(self._forward_queue) + len(self._anomaly_queue)
        health = NodeHealth.HEALTHY
        if queue_depth > 5000:
            health = NodeHealth.OVERLOADED
        elif queue_depth > 1000:
            health = NodeHealth.DEGRADED

        return EdgeNodeStatus(
            node_id=NODE_ID,
            tier=EdgeTier.MICRO_EDGE,
            health=health,
            queue_depth=queue_depth,
            uptime_s=time.monotonic() - self._start_time,
        )

    def _kafka_send(self, topic: str, payload: dict) -> None:
        """Send to Kafka using cached producer."""
        if self._producer is None:
            try:
                from kafka import KafkaProducer
                self._producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    acks=1,  # acks=1 for low-latency at Tier 1
                    retries=1,
                    linger_ms=5,
                    compression_type="snappy",
                    max_block_ms=2000,
                )
            except Exception as exc:
                log.error("Kafka producer init failed: %s", exc)
                return
        try:
            self._producer.send(topic, value=json.dumps(payload).encode())
        except Exception as exc:
            log.error("Kafka send failed topic=%s: %s", topic, exc)

    async def run_loop(self, interval_ms: int = WINDOW_MS) -> None:
        """Main processing loop. Runs at window interval (e.g., every 100ms)."""
        self._running = True
        interval_s = interval_ms / 1000.0
        log.info("Sensor hub processing loop started: interval=%dms node=%s", interval_ms, NODE_ID)
        node_health_gauge.set(0)

        batch_features: list[SensorFeatures] = []
        batch_anomalies: list[AnomalyFlag] = []

        while self._running:
            features, anomalies = self.process_cycle()
            batch_features.extend(features)
            batch_anomalies.extend(anomalies)

            # Forward in batches for efficiency
            if len(batch_features) >= BATCH_FORWARD_SIZE or batch_anomalies:
                self.forward_to_station(batch_features, batch_anomalies)
                batch_features = []
                batch_anomalies = []

            await asyncio.sleep(interval_s)

    def stop(self) -> None:
        self._running = False
        if self._producer:
            try:
                self._producer.flush(timeout=2)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI service (for health/metrics + simulation input)
# ══════════════════════════════════════════════════════════════════════════════

def create_app() -> "FastAPI":
    """Create FastAPI app for micro-edge sensor hub."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    app = FastAPI(title=f"RailOS Micro-Edge Sensor Hub ({NODE_ID})", docs_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    hub = SensorHub()

    # Register default sensor channels for this node
    hub.register_channel(f"{NODE_ID}-accel-x", SensorType.ACCELEROMETER, 4000)
    hub.register_channel(f"{NODE_ID}-accel-y", SensorType.ACCELEROMETER, 4000)
    hub.register_channel(f"{NODE_ID}-accel-z", SensorType.ACCELEROMETER, 4000)
    hub.register_channel(f"{NODE_ID}-acoustic", SensorType.ACOUSTIC, 48000)
    hub.register_channel(f"{NODE_ID}-temp", SensorType.TEMPERATURE, 10)
    hub.register_channel(f"{NODE_ID}-wheel-load", SensorType.WHEEL_LOAD, 1000)

    class IngestPayload(BaseModel):
        sensor_id: str
        values: list[float]

    class BatchIngestPayload(BaseModel):
        readings: list[IngestPayload]

    @app.on_event("startup")
    async def startup():
        try:
            start_http_server(METRICS_PORT)
        except OSError:
            pass  # port already in use by another service
        # Start processing loop in background
        asyncio.create_task(hub.run_loop())

    @app.get("/health")
    def health():
        status = hub.get_status()
        return {"status": "ok", "node_id": NODE_ID, "health": status.health.name,
                "queue_depth": status.queue_depth, "uptime_s": round(status.uptime_s, 1)}

    @app.post("/api/v1/ingest")
    def ingest_samples(payload: IngestPayload):
        """Simulate sensor data ingestion (for testing without real hardware)."""
        hub.ingest(payload.sensor_id, payload.values)
        return {"accepted": len(payload.values), "sensor_id": payload.sensor_id}

    @app.post("/api/v1/ingest/batch")
    def ingest_batch(payload: BatchIngestPayload):
        """Batch ingest multiple sensors at once."""
        total = 0
        for reading in payload.readings:
            hub.ingest(reading.sensor_id, reading.values)
            total += len(reading.values)
        return {"accepted": total, "channels": len(payload.readings)}

    @app.get("/api/v1/status")
    def status():
        return hub.get_status().to_dict()

    @app.get("/api/v1/channels")
    def channels():
        return {"channels": [
            {"sensor_id": ch.sensor_id, "type": ch.sensor_type.name,
             "rate_hz": ch.sample_rate_hz, "buffer_count": ch.ring_buffer.count}
            for ch in hub._channels.values()
        ]}

    app._hub = hub  # expose for testing
    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("APP_PORT", "8090")), log_config=None)
