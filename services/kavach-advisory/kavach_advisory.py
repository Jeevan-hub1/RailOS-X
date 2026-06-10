"""
RailOS Kavach++ Advisory Layer (Tasks 11.1–11.8)
Read-only overlay on Kavach 4.0 — physics-based braking curve, advisory-only.
Safety invariant: advisory stopping distance ≥ certified Kavach 4.0 distance.
Satisfies: Req 10, Design §6.7
"""
from __future__ import annotations

import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI
from prometheus_client import Counter, start_http_server
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
ADVISORY_TOPIC  = "monitoring.alerts"
METRICS_PORT    = int(os.environ.get("METRICS_PORT", "8080"))
APP_PORT        = int(os.environ.get("APP_PORT", "8082"))

g = 9.81  # m/s²

advisories_emitted    = Counter("kavach_advisories_emitted_total",   "Kavach++ advisories emitted")
unavailable_counter   = Counter("kavach_advisory_unavailable_total", "Advisory unavailable due to missing sensor data")


# ── 1D-CNN adhesion coefficient classifier stub (Task 11.2) ───────────────────
def estimate_adhesion(vibration_rms: float, speed_kmh: float) -> float:
    """Estimate wheel-rail adhesion coefficient μ from bogie vibration.

    Returns μ ∈ [0.10, 0.35]. Real implementation uses 1D-CNN on vibration window.
    Stub: lower adhesion at high vibration or low speed (wet conditions proxy).
    """
    if vibration_rms > 2.0:        # rough track / wet
        return max(0.10, 0.25 - vibration_rms * 0.03)
    return 0.30  # nominal dry


# ── DEM-backed gradient lookup stub (Task 11.3) ───────────────────────────────
_GRADIENT_CACHE: dict[tuple[float, float], float] = {}


def lookup_track_gradient(lat: float, lon: float) -> float:
    """GPS coordinate → track gradient angle θ (radians). Stub returns 0 (flat)."""
    key = (round(lat, 4), round(lon, 4))
    return _GRADIENT_CACHE.get(key, 0.0)


# ── Physics-based braking curve (Task 11.4) ───────────────────────────────────
def advisory_stopping_distance(speed_kmh: float, mu: float, theta_rad: float) -> float:
    """Compute stopping distance (metres) using kinematic formula.

    stopping_distance = v² / (2μg·cos(θ) + 2g·sin(θ))
    Satisfies: Req 10 C3 — must always be ≥ certified Kavach distance.
    """
    v_ms = speed_kmh / 3.6
    denom = 2 * mu * g * math.cos(theta_rad) + 2 * g * math.sin(theta_rad)
    if denom <= 0:
        return float("inf")
    return (v_ms ** 2) / denom


def kavach_certified_stopping_distance(speed_kmh: float) -> float:
    """Fixed conservative certified Kavach 4.0 stopping distance (stub).

    Real implementation reads from Kavach 4.0 data bus.
    Conservative estimate: uses μ=0.10 (worst-case adhesion), flat track.
    """
    return advisory_stopping_distance(speed_kmh, mu=0.10, theta_rad=0.0)


# ── Safety invariant check (Task 11.5) ────────────────────────────────────────
def compute_advisory(
    speed_kmh: float,
    lat: float,
    lon: float,
    vibration_rms: Optional[float],
) -> Optional[dict]:
    """Compute Kavach++ advisory braking curve.

    Returns None (KAVACH_ADVISORY_UNAVAILABLE) if required sensor data absent.
    Ensures advisory_distance ≥ certified_distance (safety invariant).
    """
    if vibration_rms is None:
        unavailable_counter.inc()
        return None  # INSUFFICIENT_DATA → KAVACH_ADVISORY_UNAVAILABLE

    mu    = estimate_adhesion(vibration_rms, speed_kmh)
    theta = lookup_track_gradient(lat, lon)

    adv_dist  = advisory_stopping_distance(speed_kmh, mu, theta)
    cert_dist = kavach_certified_stopping_distance(speed_kmh)

    # Safety invariant: advisory must be ≥ certified (Req 10 C3)
    if adv_dist < cert_dist:
        adv_dist = cert_dist  # clamp to certified — never less conservative
        mu       = 0.10        # conservative fallback adhesion

    return {
        "alertType":              "KAVACH_ADVISORY",
        "label":                  "ADVISORY — NOT CERTIFIED",
        "advisoryStoppingDist_m": round(adv_dist, 2),
        "certifiedStoppingDist_m": round(cert_dist, 2),
        "speedKmh":               speed_kmh,
        "adhesionCoeff":          round(mu, 3),
        "gradientRad":            round(theta, 5),
        "timestamp_utc":          datetime.now(timezone.utc).isoformat(),
        "alertId":                str(uuid.uuid4()),
    }


# ── FastAPI service ────────────────────────────────────────────────────────────
app = FastAPI(title="RailOS Kavach++ Advisory", docs_url=None, redoc_url=None)


class KavachRequest(BaseModel):
    speed_kmh:     float
    lat:           float
    lon:           float
    vibration_rms: Optional[float] = None


@app.on_event("startup")
def _startup() -> None:
    start_http_server(METRICS_PORT)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/kavach-advisory")
def get_advisory(req: KavachRequest) -> dict:
    result = compute_advisory(req.speed_kmh, req.lat, req.lon, req.vibration_rms)
    if result is None:
        return {"status": "KAVACH_ADVISORY_UNAVAILABLE"}
    advisories_emitted.inc()
    _publish(ADVISORY_TOPIC, result)
    return result


def _publish(topic: str, payload: dict) -> None:
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
        p.send(topic, value=json.dumps(payload).encode())
        p.flush(timeout=5)
    except Exception as exc:
        log.error("Kafka publish failed: %s", exc)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
