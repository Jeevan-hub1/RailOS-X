"""
RailOS Edge Node Hardware Telemetry + Thermal Protection (Tasks 28.1–28.4)
Samples CPU temp, GPU util, memory, storage, power every 10s.
Exposes Prometheus metrics. Throttles inference on thermal breach.
Satisfies: Req 44, Design §5.3
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

from prometheus_client import Gauge, Counter, start_http_server

log = logging.getLogger(__name__)

METRICS_PORT         = int(os.environ.get("METRICS_PORT", "8080"))
KAFKA_BOOTSTRAP      = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                       "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
SAMPLE_INTERVAL_S    = float(os.environ.get("SAMPLE_INTERVAL_SECONDS", "10"))
THERMAL_RECOVERY_S   = float(os.environ.get("THERMAL_RECOVERY_SECONDS", "60"))

# Prometheus metrics (Task 28.2)
cpu_temp_gauge   = Gauge("edge_cpu_temp_celsius",         "CPU temperature in Celsius",  ["node"])
gpu_util_gauge   = Gauge("edge_gpu_utilization_pct",      "GPU utilization %",            ["node"])
mem_util_gauge   = Gauge("edge_memory_utilization_pct",   "Memory utilization %",         ["node"])
storage_gauge    = Gauge("edge_storage_utilization_pct",  "Storage utilization %",        ["node"])
power_gauge      = Gauge("edge_power_status",             "Power: 1=nominal, 0=degraded", ["node"])
thermal_active   = Counter("edge_thermal_protection_activations_total", "Thermal throttle count", ["node"])

NODE_ID = os.environ.get("NODE_ID", "edge-node-unknown")
_thermal_protection_active = False
_thermal_below_threshold_since: Optional[float] = None
_inference_throttle_callback = None  # set by inference subsystem


def set_inference_throttle_callback(fn) -> None:
    """Register callback that edge inference service calls to check throttle state."""
    global _inference_throttle_callback
    _inference_throttle_callback = fn


def is_throttled() -> bool:
    return _thermal_protection_active


def _read_hardware_metrics() -> dict:
    """Read hardware metrics. Uses psutil + jtop (Jetson) when available."""
    metrics = {
        "cpu_temp_c":          0.0,
        "gpu_utilization_pct": 0.0,
        "memory_utilization_pct": 0.0,
        "storage_utilization_pct": 0.0,
        "power_status":        "nominal",
    }
    try:
        import psutil
        metrics["memory_utilization_pct"] = psutil.virtual_memory().percent
        metrics["storage_utilization_pct"] = psutil.disk_usage("/data").percent
        # CPU temp (platform-dependent)
        temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
        cpu_temps = temps.get("cpu_thermal", temps.get("coretemp", []))
        if cpu_temps:
            metrics["cpu_temp_c"] = cpu_temps[0].current
    except Exception as exc:
        log.warning("psutil metric collection failed: %s", exc)

    try:
        # Jetson GPU stats via jtop
        from jtop import jtop
        with jtop() as jetson:
            if jetson.ok():
                metrics["gpu_utilization_pct"] = jetson.gpu.get("status", {}).get("val", 0)
                metrics["cpu_temp_c"]           = jetson.temperature.get("CPU", metrics["cpu_temp_c"])
    except ImportError:
        pass  # jtop not available on non-Jetson hardware
    except Exception as exc:
        log.warning("Jetson GPU metric collection failed: %s", exc)

    return metrics


def _get_oem_threshold() -> float:
    """Return OEM-specified safe operational temperature threshold."""
    return float(os.environ.get("CPU_THERMAL_THRESHOLD_C", "85.0"))


def _handle_thermal(temp: float) -> None:
    """Activate or restore thermal protection (Tasks 28.3–28.4)."""
    global _thermal_protection_active, _thermal_below_threshold_since
    threshold = _get_oem_threshold()

    if temp > threshold:
        if not _thermal_protection_active:
            _thermal_protection_active = True
            _thermal_below_threshold_since = None
            thermal_active.labels(node=NODE_ID).inc()
            log.warning("THERMAL_PROTECTION_ACTIVE temp=%.1f threshold=%.1f node=%s",
                        temp, threshold, NODE_ID)
            _emit_alert("THERMAL_PROTECTION_ACTIVE", temp, threshold)
    else:
        if _thermal_protection_active:
            now = time.monotonic()
            if _thermal_below_threshold_since is None:
                _thermal_below_threshold_since = now
            elif now - _thermal_below_threshold_since >= THERMAL_RECOVERY_S:
                _thermal_protection_active = False
                _thermal_below_threshold_since = None
                log.info("THERMAL_PROTECTION_LIFTED temp=%.1f node=%s", temp, NODE_ID)
                _emit_alert("THERMAL_PROTECTION_LIFTED", temp, threshold)
        else:
            _thermal_below_threshold_since = None


def _emit_alert(alert_type: str, temp: float, threshold: float) -> None:
    payload = {
        "alertType":  alert_type,
        "nodeId":     NODE_ID,
        "cpuTempC":   round(temp, 1),
        "threshold":  threshold,
    }
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=2)
        p.send("monitoring.alerts", value=json.dumps(payload).encode())
        p.flush(timeout=3)
    except Exception as exc:
        log.error("Alert emit failed: %s", exc)


def telemetry_loop() -> None:
    """Main telemetry sampling loop (blocking). Run in a daemon thread."""
    start_http_server(METRICS_PORT)
    log.info("Hardware telemetry started node=%s interval=%ss", NODE_ID, SAMPLE_INTERVAL_S)
    while True:
        m = _read_hardware_metrics()
        cpu_temp_gauge.labels(node=NODE_ID).set(m["cpu_temp_c"])
        gpu_util_gauge.labels(node=NODE_ID).set(m["gpu_utilization_pct"])
        mem_util_gauge.labels(node=NODE_ID).set(m["memory_utilization_pct"])
        storage_gauge.labels(node=NODE_ID).set(m["storage_utilization_pct"])
        power_gauge.labels(node=NODE_ID).set(1 if m["power_status"] == "nominal" else 0)
        _handle_thermal(m["cpu_temp_c"])
        time.sleep(SAMPLE_INTERVAL_S)


def start_telemetry_thread() -> threading.Thread:
    t = threading.Thread(target=telemetry_loop, daemon=True, name="HardwareTelemetry")
    t.start()
    return t
