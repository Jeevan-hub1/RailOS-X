"""
RailOS Geographic Failure Isolation (Tasks 25.1–25.3)
Partitions Corridor into geographic zones; on repeated SUBSYSTEM_DEGRADED alerts
from one zone, isolates that zone's Flink processing without affecting others.
Satisfies: Req 41, Design §10.3
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                  "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")

# Default corridor zone definitions (Task 25.1)
# Each zone covers a contiguous set of stations/segments
DEFAULT_ZONES = {
    "scr-north":  {"stations": ["HYB", "SC",  "BZA"], "segments": ["SEG-001", "SEG-002", "SEG-003"]},
    "scr-central":{"stations": ["GTL", "GNT", "NZB"], "segments": ["SEG-010", "SEG-011", "SEG-012"]},
    "scr-south":  {"stations": ["MAS", "AJJ", "RU"],  "segments": ["SEG-020", "SEG-021", "SEG-022"]},
    "scr-west":   {"stations": ["SUR", "WD",  "PVR"], "segments": ["SEG-030", "SEG-031", "SEG-032"]},
}

# Zone isolation state
_zone_degraded:        dict[str, bool] = {z: False for z in DEFAULT_ZONES}
_zone_alert_counts:    dict[str, int]  = {z: 0 for z in DEFAULT_ZONES}
_zone_alert_threshold: int = int(os.environ.get("ZONE_DEGRADED_THRESHOLD", "3"))
_lock = threading.Lock()


def get_zone_for_station(station_id: str) -> str | None:
    """Return the zone name for a given station ID."""
    for zone, config in DEFAULT_ZONES.items():
        if station_id in config.get("stations", []):
            return zone
    return None


def get_zone_for_segment(segment_id: str) -> str | None:
    """Return the zone name for a given segment ID."""
    for zone, config in DEFAULT_ZONES.items():
        if segment_id in config.get("segments", []):
            return zone
    return None


def is_zone_isolated(zone: str) -> bool:
    """Return True if a zone is currently in degraded/isolated mode (Task 25.2)."""
    return _zone_degraded.get(zone, False)


def record_zone_alert(zone: str, alert_type: str) -> bool:
    """Record a SUBSYSTEM_DEGRADED alert for a zone. Returns True if zone enters isolation."""
    with _lock:
        _zone_alert_counts[zone] = _zone_alert_counts.get(zone, 0) + 1
        if (not _zone_degraded.get(zone, False) and
                _zone_alert_counts[zone] >= _zone_alert_threshold):
            _zone_degraded[zone] = True
            log.warning("ZONE_ISOLATED zone=%s alert_count=%d",
                        zone, _zone_alert_counts[zone])
            _emit_zone_status(zone, "ISOLATED")
            _isolate_flink_processing_unit(zone)
            return True
    return False


def restore_zone(zone: str) -> None:
    """Restore a zone from isolation."""
    with _lock:
        _zone_degraded[zone] = False
        _zone_alert_counts[zone] = 0
    log.info("ZONE_RESTORED zone=%s", zone)
    _emit_zone_status(zone, "RESTORED")


def get_zone_status() -> dict[str, dict]:
    """Return current isolation status for all zones (used by Digital Twin Task 25.3)."""
    with _lock:
        return {
            zone: {
                "isolated":    _zone_degraded.get(zone, False),
                "alertCount":  _zone_alert_counts.get(zone, 0),
                "stations":    DEFAULT_ZONES[zone]["stations"],
                "segments":    DEFAULT_ZONES[zone]["segments"],
            }
            for zone in DEFAULT_ZONES
        }


def _isolate_flink_processing_unit(zone: str) -> None:
    """Scale down Flink task managers labeled for this zone (Task 25.2)."""
    try:
        import subprocess
        label = f"railos.io/zone={zone}"
        result = subprocess.run(
            ["kubectl", "scale", "deployment", "-n", "railos",
             "-l", label, "--replicas=0"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            log.info("Flink processing unit isolated for zone=%s", zone)
        else:
            log.warning("kubectl scale failed for zone=%s: %s", zone, result.stderr)
    except Exception as exc:
        log.error("Zone isolation command failed: %s", exc)


def _emit_zone_status(zone: str, status: str) -> None:
    payload = {
        "alertType":    f"ZONE_{status}",
        "zone":         zone,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "stations":     DEFAULT_ZONES.get(zone, {}).get("stations", []),
    }
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
        p.send("monitoring.alerts", value=json.dumps(payload).encode())
        p.flush(timeout=5)
    except Exception as exc:
        log.error("Zone status emit failed: %s", exc)
