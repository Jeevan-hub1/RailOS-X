"""
RailOS-X Edge Computing Protocol Definitions
Shared data models, enumerations, and message schemas for the 3-tier edge layer.

Architecture:
  Tier 1 (Micro-Edge)  → sub-ms sensor fusion, anomaly flagging, raw signal → features
  Tier 2 (Station Edge) → local ML inference, multi-sensor correlation, 5s decision loop
  Tier 3 (Zone Compute) → cross-station coordination, federated learning, SLA enforcement

Wire format: MessagePack over MQTT (Tier 1→2), Protobuf/JSON over gRPC/HTTP (Tier 2→3)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import IntEnum, auto
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════════════════
# Enumerations
# ══════════════════════════════════════════════════════════════════════════════

class SensorType(IntEnum):
    """Sensor modalities supported at Micro-Edge tier."""
    ACCELEROMETER  = 1   # Bogie/rail vibration (3-axis, 4kHz)
    ACOUSTIC       = 2   # Ultrasonic / airborne acoustic (48kHz)
    TEMPERATURE    = 3   # Axle box / rail temperature (0.1°C resolution)
    WHEEL_LOAD     = 4   # Strain gauge wheel/rail force (1kHz)
    GPS            = 5   # GNSS position + velocity (10Hz)
    LIDAR          = 6   # Track profile / clearance (100Hz)
    CAMERA         = 7   # Vision defect detection (30fps)
    CURRENT_LOOP   = 8   # Track circuit / signaling current (1kHz)
    HUMIDITY       = 9   # Environmental humidity (1Hz)
    WIND_SPEED     = 10  # Anemometer (10Hz)


class EdgeTier(IntEnum):
    MICRO_EDGE    = 1   # Trackside/bogie MCU (FPGA + ARM Cortex-M)
    STATION_EDGE  = 2   # Station compute (Jetson Orin NX / AGX)
    ZONE_COMPUTE  = 3   # Zone controller (GPU cluster, 4–8 nodes)


class AlertSeverity(IntEnum):
    INFO     = 0
    WARNING  = 1
    CRITICAL = 2
    EMERGENCY = 3


class ProcessingPriority(IntEnum):
    """Determines scheduling priority in inference queues."""
    REAL_TIME   = 0   # Safety-critical, preempts everything (brake advisory)
    HIGH        = 1   # Defect detection, anomaly alerts
    NORMAL      = 2   # Predictive maintenance, trend analysis
    BACKGROUND  = 3   # Model retraining, analytics


class NodeHealth(IntEnum):
    HEALTHY     = 0
    DEGRADED    = 1
    OVERLOADED  = 2
    OFFLINE     = 3


class SyncStrategy(IntEnum):
    """Data sync strategy between tiers."""
    IMMEDIATE   = 0   # Push every sample (safety-critical only)
    BATCHED     = 1   # Batch every N samples or T seconds
    ON_ANOMALY  = 2   # Push only when anomaly detected
    PERIODIC    = 3   # Fixed interval summaries


# ══════════════════════════════════════════════════════════════════════════════
# Core Data Models
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class SensorReading:
    """Raw sensor reading from Tier 1 micro-edge node."""
    sensor_id:      str
    sensor_type:    SensorType
    node_id:        str
    timestamp_ns:   int               # nanosecond-precision monotonic clock
    values:         list[float]        # multi-axis / multi-sample window
    sample_rate_hz: int = 1000
    quality:        float = 1.0       # 0.0 = failed, 1.0 = nominal
    metadata:       dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sensor_type"] = self.sensor_type.value
        return d


@dataclass(slots=True)
class SensorFeatures:
    """Pre-processed feature vector extracted from raw readings."""
    sensor_id:    str
    node_id:      str
    timestamp_ns: int
    features:     dict[str, float]   # named feature → value
    window_ms:    int = 100          # analysis window duration
    source_type:  SensorType = SensorType.ACCELEROMETER

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        return d


@dataclass(slots=True)
class AnomalyFlag:
    """Anomaly detected at micro-edge — forwarded to station for correlation."""
    flag_id:        str = field(default_factory=lambda: str(uuid.uuid4()))
    sensor_id:      str = ""
    node_id:        str = ""
    anomaly_type:   str = ""          # e.g., "vibration_spike", "thermal_runaway"
    severity:       AlertSeverity = AlertSeverity.WARNING
    confidence:     float = 0.0       # 0.0–1.0 from micro-edge model
    timestamp_ns:   int = 0
    feature_snapshot: dict[str, float] = field(default_factory=dict)
    context:        dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass(slots=True)
class InferenceRequest:
    """Request for ML inference at Station Edge (Tier 2)."""
    request_id:     str = field(default_factory=lambda: str(uuid.uuid4()))
    model_id:       str = ""
    model_version:  str = ""
    priority:       ProcessingPriority = ProcessingPriority.NORMAL
    input_features: dict[str, Any] = field(default_factory=dict)
    timestamp_ns:   int = field(default_factory=time.time_ns)
    deadline_ms:    int = 5000        # max acceptable latency
    source_node:    str = ""
    batch_key:      Optional[str] = None   # group for batching

    def to_dict(self) -> dict:
        d = asdict(self)
        d["priority"] = self.priority.value
        return d


@dataclass(slots=True)
class InferenceResult:
    """Result from Station Edge inference engine."""
    request_id:     str = ""
    model_id:       str = ""
    predictions:    dict[str, Any] = field(default_factory=dict)
    confidence:     float = 0.0
    latency_ms:     float = 0.0
    timestamp_ns:   int = field(default_factory=time.time_ns)
    warnings:       list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class EdgeNodeStatus:
    """Health/status report from any tier."""
    node_id:        str = ""
    tier:           EdgeTier = EdgeTier.MICRO_EDGE
    health:         NodeHealth = NodeHealth.HEALTHY
    cpu_pct:        float = 0.0
    gpu_pct:        float = 0.0
    memory_pct:     float = 0.0
    temperature_c:  float = 0.0
    inference_qps:  float = 0.0
    queue_depth:    int = 0
    uptime_s:       float = 0.0
    model_versions: dict[str, str] = field(default_factory=dict)
    timestamp_ns:   int = field(default_factory=time.time_ns)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tier"] = self.tier.value
        d["health"] = self.health.value
        return d


@dataclass(slots=True)
class ModelDeployment:
    """Model deployment instruction from Zone Compute → Station Edge."""
    deployment_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    model_id:         str = ""
    model_version:    str = ""
    artifact_url:     str = ""         # S3/MinIO URL
    checksum_sha256:  str = ""
    target_nodes:     list[str] = field(default_factory=list)
    rollout_strategy: str = "canary"   # canary | rolling | blue-green
    canary_pct:       float = 10.0
    priority:         ProcessingPriority = ProcessingPriority.NORMAL
    deadline_utc:     Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["priority"] = self.priority.value
        return d


@dataclass(slots=True)
class ZoneSLA:
    """SLA requirements for a compute zone."""
    zone_id:              str = ""
    max_inference_ms:     int = 100      # P99 inference latency
    min_availability_pct: float = 99.9
    max_queue_depth:      int = 1000
    min_throughput_qps:   float = 500.0
    thermal_ceiling_c:    float = 85.0
    failover_enabled:     bool = True


# ══════════════════════════════════════════════════════════════════════════════
# Ring Buffer for High-Frequency Sensor Data
# ══════════════════════════════════════════════════════════════════════════════

class RingBuffer:
    """Lock-free-style fixed-size ring buffer for streaming sensor samples.
    
    Optimized for Tier 1 micro-edge where we process at 1–4kHz per channel.
    Uses pre-allocated list to avoid GC pressure.
    """
    __slots__ = ('_buf', '_capacity', '_head', '_count')

    def __init__(self, capacity: int = 4096) -> None:
        self._buf: list[float] = [0.0] * capacity
        self._capacity = capacity
        self._head = 0
        self._count = 0

    @property
    def count(self) -> int:
        return min(self._count, self._capacity)

    @property
    def is_full(self) -> bool:
        return self._count >= self._capacity

    def push(self, value: float) -> None:
        """Append a sample. O(1), overwrites oldest on full."""
        self._buf[self._head] = value
        self._head = (self._head + 1) % self._capacity
        self._count += 1

    def push_batch(self, values: list[float]) -> None:
        """Batch push for efficiency. Avoids per-element modulo."""
        n = len(values)
        if n >= self._capacity:
            # Overwrite entire buffer
            self._buf[:] = values[-self._capacity:]
            self._head = 0
            self._count = self._capacity
            return
        space_at_end = self._capacity - self._head
        if n <= space_at_end:
            self._buf[self._head:self._head + n] = values
        else:
            self._buf[self._head:] = values[:space_at_end]
            self._buf[:n - space_at_end] = values[space_at_end:]
        self._head = (self._head + n) % self._capacity
        self._count += n

    def get_window(self, n: int) -> list[float]:
        """Get the last n samples (most recent first)."""
        available = self.count
        n = min(n, available)
        result = []
        idx = (self._head - 1) % self._capacity
        for _ in range(n):
            result.append(self._buf[idx])
            idx = (idx - 1) % self._capacity
        return result

    def get_all_ordered(self) -> list[float]:
        """Get all samples in chronological order (oldest first)."""
        available = self.count
        if available < self._capacity:
            return self._buf[:available]
        # Buffer is full — start from head (oldest)
        return self._buf[self._head:] + self._buf[:self._head]

    def clear(self) -> None:
        self._head = 0
        self._count = 0


# ══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ══════════════════════════════════════════════════════════════════════════════

def generate_node_id(tier: EdgeTier, station: str, index: int = 0) -> str:
    """Generate deterministic node ID: tier-station-index."""
    prefix = {EdgeTier.MICRO_EDGE: "me", EdgeTier.STATION_EDGE: "se", EdgeTier.ZONE_COMPUTE: "zc"}
    return f"{prefix[tier]}-{station}-{index:03d}"


def timestamp_ns() -> int:
    """High-resolution monotonic timestamp in nanoseconds."""
    return time.time_ns()


def latency_ms(start_ns: int) -> float:
    """Compute latency in ms from a start timestamp."""
    return (time.time_ns() - start_ns) / 1_000_000
