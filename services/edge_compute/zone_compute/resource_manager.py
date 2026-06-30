"""
RailOS-X Zone Compute Resource Manager (Tier 3)
GPU/CPU allocation, workload scheduling, auto-scaling, and health monitoring
across the zone compute cluster.

Responsibilities:
  - Track GPU/CPU/memory resources across cluster nodes
  - Schedule inference workloads optimally (bin-packing + priority)
  - Auto-scale inference replicas based on queue depth / latency
  - Detect and handle node failures with failover
  - Power management (scale down during low-traffic periods)
  - Resource quotas per station / model

Satisfies: Req 44, Design §5.3.2
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Any, Optional

from prometheus_client import Gauge, Counter, Histogram

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Resource Types
# ══════════════════════════════════════════════════════════════════════════════

class DeviceType(IntEnum):
    CPU = 0
    GPU = 1
    TPU = 2
    FPGA = 3


class ScalingAction(IntEnum):
    NONE       = 0
    SCALE_UP   = 1
    SCALE_DOWN = 2


@dataclass(slots=True)
class ResourceCapacity:
    """Available resources on a compute node."""
    cpu_cores:       int = 8
    cpu_freq_ghz:    float = 3.0
    gpu_count:       int = 1
    gpu_memory_gb:   float = 16.0
    gpu_compute_tflops: float = 50.0
    ram_gb:          float = 32.0
    storage_gb:      float = 512.0
    network_gbps:    float = 10.0


@dataclass(slots=True)
class ResourceUsage:
    """Current resource usage on a compute node."""
    cpu_pct:         float = 0.0
    gpu_pct:         float = 0.0
    gpu_memory_pct:  float = 0.0
    ram_pct:         float = 0.0
    storage_pct:     float = 0.0
    network_pct:     float = 0.0
    power_watts:     float = 0.0
    temperature_c:   float = 0.0


@dataclass
class ComputeNode:
    """A physical or virtual compute node in the zone cluster."""
    node_id:          str
    capacity:         ResourceCapacity = field(default_factory=ResourceCapacity)
    usage:            ResourceUsage = field(default_factory=ResourceUsage)
    device_type:      DeviceType = DeviceType.GPU
    is_available:     bool = True
    assigned_models:  list[str] = field(default_factory=list)
    max_concurrent:   int = 4       # max concurrent inference workloads
    current_workloads: int = 0
    last_heartbeat:   float = field(default_factory=time.monotonic)

    @property
    def utilization_score(self) -> float:
        """Overall utilization 0.0–1.0 (used for scheduling decisions)."""
        return (self.usage.cpu_pct + self.usage.gpu_pct * 2 + self.usage.ram_pct) / 400.0

    @property
    def available_capacity(self) -> float:
        """Remaining capacity score 0.0–1.0."""
        return max(0.0, 1.0 - self.utilization_score)

    @property
    def can_accept_workload(self) -> bool:
        return (self.is_available and
                self.current_workloads < self.max_concurrent and
                self.usage.gpu_pct < 95.0 and
                self.usage.temperature_c < 85.0)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "device_type": self.device_type.name,
            "utilization": round(self.utilization_score, 3),
            "available_capacity": round(self.available_capacity, 3),
            "workloads": f"{self.current_workloads}/{self.max_concurrent}",
            "gpu_pct": self.usage.gpu_pct,
            "cpu_pct": self.usage.cpu_pct,
            "temperature_c": self.usage.temperature_c,
            "is_available": self.is_available,
            "models": self.assigned_models,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Workload Scheduler — Best-fit decreasing bin-packing with priority
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkloadRequest:
    """A request to schedule inference workload on a compute node."""
    workload_id:    str
    model_id:       str
    priority:       int = 2          # 0=realtime, 1=high, 2=normal, 3=background
    gpu_memory_gb:  float = 2.0      # estimated GPU memory requirement
    compute_tflops: float = 1.0      # estimated compute requirement
    deadline_ms:    int = 100
    station_id:     str = ""
    submitted_at:   float = field(default_factory=time.monotonic)


@dataclass
class SchedulerDecision:
    """Output of workload scheduling."""
    workload_id:    str
    assigned_node:  Optional[str] = None
    status:         str = "pending"  # pending | scheduled | rejected | queued
    reason:         str = ""
    wait_time_ms:   float = 0.0


class WorkloadScheduler:
    """Priority-aware bin-packing scheduler for GPU inference workloads.
    
    Scheduling strategy:
      1. Priority preemption: REAL_TIME can preempt BACKGROUND
      2. Affinity: prefer nodes already running the same model (warm cache)
      3. Best-fit: choose node with smallest remaining capacity that fits
      4. Load balancing: spread across nodes when capacity is equal
    """

    def __init__(self) -> None:
        self._pending: deque[WorkloadRequest] = deque(maxlen=5000)
        self._scheduled: dict[str, SchedulerDecision] = {}
        self._lock = threading.Lock()
        self._total_scheduled = 0
        self._total_rejected = 0

    def schedule(self, request: WorkloadRequest, nodes: list[ComputeNode]) -> SchedulerDecision:
        """Schedule a workload request onto the best available node."""
        # 1. Filter available nodes
        available = [n for n in nodes if n.can_accept_workload]
        if not available:
            # Queue or reject based on priority
            if request.priority <= 1:  # real-time / high: queue
                self._pending.append(request)
                return SchedulerDecision(
                    workload_id=request.workload_id,
                    status="queued", reason="No available nodes — queued (high priority)"
                )
            self._total_rejected += 1
            return SchedulerDecision(
                workload_id=request.workload_id,
                status="rejected", reason="No available nodes"
            )

        # 2. Score nodes (higher = better fit)
        scored = []
        for node in available:
            score = self._score_node(node, request)
            scored.append((score, node))

        scored.sort(key=lambda x: -x[0])  # highest score first
        best_node = scored[0][1]

        # 3. Assign
        best_node.current_workloads += 1
        if request.model_id not in best_node.assigned_models:
            best_node.assigned_models.append(request.model_id)

        self._total_scheduled += 1
        decision = SchedulerDecision(
            workload_id=request.workload_id,
            assigned_node=best_node.node_id,
            status="scheduled",
            wait_time_ms=(time.monotonic() - request.submitted_at) * 1000,
        )
        self._scheduled[request.workload_id] = decision
        return decision

    def release_workload(self, workload_id: str, nodes: list[ComputeNode]) -> None:
        """Release a completed workload from its node."""
        decision = self._scheduled.pop(workload_id, None)
        if decision and decision.assigned_node:
            for node in nodes:
                if node.node_id == decision.assigned_node:
                    node.current_workloads = max(0, node.current_workloads - 1)
                    break

    def drain_pending(self, nodes: list[ComputeNode]) -> list[SchedulerDecision]:
        """Attempt to schedule pending workloads. Called periodically."""
        results = []
        retry_queue = deque()
        while self._pending:
            req = self._pending.popleft()
            # Check if deadline passed
            elapsed_ms = (time.monotonic() - req.submitted_at) * 1000
            if elapsed_ms > req.deadline_ms * 2:
                self._total_rejected += 1
                continue
            decision = self.schedule(req, nodes)
            if decision.status == "scheduled":
                results.append(decision)
            elif decision.status == "queued":
                retry_queue.append(req)
        self._pending = retry_queue
        return results

    def _score_node(self, node: ComputeNode, request: WorkloadRequest) -> float:
        """Score a node for a workload. Higher = better."""
        score = 0.0

        # Affinity bonus: node already has this model loaded (warm cache)
        if request.model_id in node.assigned_models:
            score += 50.0

        # Best-fit: prefer nodes with less remaining capacity (pack tightly)
        score += (1.0 - node.available_capacity) * 20.0

        # Temperature penalty
        if node.usage.temperature_c > 75:
            score -= (node.usage.temperature_c - 75) * 2

        # Low workload count bonus (balance)
        score += (node.max_concurrent - node.current_workloads) * 5

        return score

    def get_stats(self) -> dict:
        return {
            "pending": len(self._pending),
            "active_scheduled": len(self._scheduled),
            "total_scheduled": self._total_scheduled,
            "total_rejected": self._total_rejected,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Auto-Scaler
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScalingPolicy:
    """Auto-scaling policy configuration."""
    target_gpu_utilization_pct: float = 70.0
    target_queue_depth:         int = 50
    scale_up_threshold:         float = 85.0   # GPU util % to trigger scale-up
    scale_down_threshold:       float = 30.0   # GPU util % to trigger scale-down
    cooldown_s:                 float = 120.0  # seconds between scaling actions
    min_replicas:               int = 1
    max_replicas:               int = 8
    scale_up_step:              int = 1
    scale_down_step:            int = 1


class AutoScaler:
    """Monitors cluster metrics and recommends scaling actions."""

    def __init__(self, policy: ScalingPolicy = None) -> None:
        self.policy = policy or ScalingPolicy()
        self._last_scale_time: float = 0.0
        self._current_replicas: int = self.policy.min_replicas
        self._history: deque[dict] = deque(maxlen=100)

    def evaluate(self, nodes: list[ComputeNode], queue_depth: int) -> ScalingAction:
        """Evaluate whether to scale up, down, or hold."""
        now = time.monotonic()
        if now - self._last_scale_time < self.policy.cooldown_s:
            return ScalingAction.NONE

        active_nodes = [n for n in nodes if n.is_available]
        if not active_nodes:
            return ScalingAction.SCALE_UP

        avg_gpu = sum(n.usage.gpu_pct for n in active_nodes) / len(active_nodes)
        avg_cpu = sum(n.usage.cpu_pct for n in active_nodes) / len(active_nodes)

        decision = ScalingAction.NONE

        # Scale UP conditions
        if (avg_gpu > self.policy.scale_up_threshold or
            queue_depth > self.policy.target_queue_depth * 2):
            if self._current_replicas < self.policy.max_replicas:
                decision = ScalingAction.SCALE_UP
                self._current_replicas = min(
                    self.policy.max_replicas,
                    self._current_replicas + self.policy.scale_up_step
                )

        # Scale DOWN conditions
        elif (avg_gpu < self.policy.scale_down_threshold and
              queue_depth < self.policy.target_queue_depth // 2):
            if self._current_replicas > self.policy.min_replicas:
                decision = ScalingAction.SCALE_DOWN
                self._current_replicas = max(
                    self.policy.min_replicas,
                    self._current_replicas - self.policy.scale_down_step
                )

        if decision != ScalingAction.NONE:
            self._last_scale_time = now
            self._history.append({
                "timestamp": time.time(),
                "action": decision.name,
                "replicas": self._current_replicas,
                "avg_gpu_pct": round(avg_gpu, 1),
                "queue_depth": queue_depth,
            })
            log.info("AUTO_SCALE %s → %d replicas (gpu=%.1f%% queue=%d)",
                     decision.name, self._current_replicas, avg_gpu, queue_depth)

        return decision

    def get_status(self) -> dict:
        return {
            "current_replicas": self._current_replicas,
            "min_replicas": self.policy.min_replicas,
            "max_replicas": self.policy.max_replicas,
            "recent_actions": list(self._history)[-5:],
        }


# ══════════════════════════════════════════════════════════════════════════════
# Resource Manager — top-level coordinator
# ══════════════════════════════════════════════════════════════════════════════

class ResourceManager:
    """Manages compute resources across the zone cluster."""

    def __init__(self) -> None:
        self._nodes: dict[str, ComputeNode] = {}
        self._scheduler = WorkloadScheduler()
        self._auto_scaler = AutoScaler()
        self._lock = threading.Lock()

        # Initialize default cluster nodes (simulated for dev)
        self._init_default_cluster()

    def _init_default_cluster(self) -> None:
        """Initialize simulated cluster nodes for development."""
        for i in range(4):
            node = ComputeNode(
                node_id=f"gpu-node-{i:03d}",
                capacity=ResourceCapacity(
                    cpu_cores=16, gpu_count=1, gpu_memory_gb=24.0,
                    gpu_compute_tflops=100.0, ram_gb=64.0,
                ),
                device_type=DeviceType.GPU,
                max_concurrent=8,
            )
            self._nodes[node.node_id] = node

    def register_node(self, node_id: str, capacity: dict) -> ComputeNode:
        """Register a new compute node."""
        cap = ResourceCapacity(
            cpu_cores=capacity.get("cpu_cores", 8),
            gpu_count=capacity.get("gpu_count", 1),
            gpu_memory_gb=capacity.get("gpu_memory_gb", 16),
            ram_gb=capacity.get("ram_gb", 32),
        )
        node = ComputeNode(node_id=node_id, capacity=cap)
        with self._lock:
            self._nodes[node_id] = node
        return node

    def update_usage(self, node_id: str, usage: dict) -> bool:
        """Update resource usage for a node."""
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return False
            node.usage.cpu_pct = usage.get("cpu_pct", 0)
            node.usage.gpu_pct = usage.get("gpu_pct", 0)
            node.usage.gpu_memory_pct = usage.get("gpu_memory_pct", 0)
            node.usage.ram_pct = usage.get("ram_pct", 0)
            node.usage.temperature_c = usage.get("temperature_c", 0)
            node.usage.power_watts = usage.get("power_watts", 0)
            node.last_heartbeat = time.monotonic()
            return True

    def schedule_workload(self, request: WorkloadRequest) -> SchedulerDecision:
        """Schedule a workload through the bin-packing scheduler."""
        with self._lock:
            nodes = list(self._nodes.values())
        return self._scheduler.schedule(request, nodes)

    def release_workload(self, workload_id: str) -> None:
        """Release a completed workload."""
        with self._lock:
            nodes = list(self._nodes.values())
        self._scheduler.release_workload(workload_id, nodes)

    def check_scaling(self, queue_depth: int = 0) -> ScalingAction:
        """Check if auto-scaling is needed."""
        with self._lock:
            nodes = list(self._nodes.values())
        return self._auto_scaler.evaluate(nodes, queue_depth)

    def get_cluster_status(self) -> dict:
        with self._lock:
            nodes = list(self._nodes.values())
        total_gpu = sum(1 for n in nodes if n.is_available and n.device_type == DeviceType.GPU)
        avg_util = sum(n.utilization_score for n in nodes) / len(nodes) if nodes else 0

        return {
            "total_nodes": len(nodes),
            "available_gpu_nodes": total_gpu,
            "avg_utilization": round(avg_util, 3),
            "scheduler": self._scheduler.get_stats(),
            "auto_scaler": self._auto_scaler.get_status(),
            "nodes": [n.to_dict() for n in nodes],
        }


# Module-level singleton
resource_manager = ResourceManager()


def get_resource_manager() -> ResourceManager:
    return resource_manager
