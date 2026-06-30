"""
RailOS Kavach++ Advisory Layer (Tasks 11.1–11.8)
Read-only overlay on Kavach 4.0 — advanced physics-based braking curve, advisory-only.
Safety invariant: advisory stopping distance >= certified Kavach 4.0 distance.

Physics model includes:
  - Multi-phase deceleration (reaction delay + service + emergency)
  - Polach adhesion model (speed-dependent creep force saturation)
  - Aerodynamic drag (Davis equation for Indian Railways)
  - Rotational inertia factor (wheelsets, axles, traction motors)
  - Brake fade (thermal degradation under sustained braking)
  - Track curvature resistance
  - Environmental factors (rain, leaf film, humidity)
  - Train composition (mass, brake weight percentage)

Satisfies: Req 10, Design section 6.7
"""
from __future__ import annotations

import json
import logging
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, start_http_server
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

# ── Physical Constants ────────────────────────────────────────────────────────
g = 9.81          # gravitational acceleration (m/s^2)
RHO_AIR = 1.225   # air density at sea level (kg/m^3)

# ── Prometheus Metrics ────────────────────────────────────────────────────────
advisories_emitted    = Counter("kavach_advisories_emitted_total", "Kavach++ advisories emitted")
unavailable_counter   = Counter("kavach_advisory_unavailable_total", "Advisory unavailable due to missing sensor data")
braking_latency       = Histogram("kavach_computation_latency_ms", "Braking curve computation time",
                                  buckets=[0.1, 0.5, 1, 2, 5, 10])

# ── Cached Kafka producer singleton ──────────────────────────────────────────
_kafka_producer = None
_kafka_producer_lock = None


def _get_producer():
    """Lazy-init a shared KafkaProducer. Avoids reconnect on every request."""
    global _kafka_producer
    if _kafka_producer is not None:
        return _kafka_producer
    try:
        from kafka import KafkaProducer
        _kafka_producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            acks="all",
            retries=3,
            linger_ms=10,           # batch small messages for throughput
            compression_type="lz4", # reduce network overhead
            max_block_ms=5000,      # don't block request thread >5s
        )
        return _kafka_producer
    except Exception as exc:
        log.error("Kafka producer init failed: %s", exc)
        return None


# ── Train Configuration ────────────────────────────────────────────────────────
@dataclass
class TrainConfig:
    """Train physical parameters for braking computation."""
    mass_tonnes:           float = 580.0    # Typical Indian EMU (12-car Vande Bharat)
    brake_weight_pct:      float = 90.0     # Brake weight / total weight (%)
    frontal_area_m2:       float = 12.5     # Cross-sectional area
    drag_coeff:            float = 0.45     # Aerodynamic drag coefficient
    rotational_inertia:    float = 1.06     # Lambda factor (1 + rotating mass / total mass)
    wheel_diameter_m:      float = 0.915    # Standard BG wheel diameter
    brake_pad_mu:          float = 0.35     # Pad-on-disc friction coefficient
    n_brake_cylinders:     int   = 48       # Number of brake cylinders
    reaction_time_s:       float = 2.0      # Driver reaction time
    propagation_time_s:    float = 3.5      # Brake pipe propagation (full train length)
    service_decel_target:  float = 0.8      # Target service brake decel (m/s^2)
    emergency_decel_max:   float = 1.2      # Max emergency brake decel (m/s^2)
    length_m:              float = 260.0    # Train length


# Default configs for common Indian Railway stock
TRAIN_CONFIGS = {
    "vande_bharat": TrainConfig(mass_tonnes=430, brake_weight_pct=100, frontal_area_m2=11.5,
                                rotational_inertia=1.08, length_m=260, reaction_time_s=1.5,
                                propagation_time_s=1.0, emergency_decel_max=1.3),
    "wap7_rajdhani": TrainConfig(mass_tonnes=980, brake_weight_pct=85, frontal_area_m2=13.0,
                                  rotational_inertia=1.05, length_m=420, reaction_time_s=2.0,
                                  propagation_time_s=4.5, emergency_decel_max=1.0),
    "wdp4d_mail": TrainConfig(mass_tonnes=1400, brake_weight_pct=75, frontal_area_m2=13.5,
                               rotational_inertia=1.04, length_m=550, reaction_time_s=2.5,
                               propagation_time_s=6.0, emergency_decel_max=0.85),
    "default": TrainConfig(),
}

_active_train = TRAIN_CONFIGS["default"]


# ── Polach Adhesion Model (Task 11.2) ─────────────────────────────────────────
def polach_adhesion(speed_kmh: float, vibration_rms: float,
                    humidity_pct: float = 50.0, leaf_contamination: bool = False) -> float:
    """Estimate wheel-rail adhesion using the Polach (2005) creep force model.

    The Polach model accounts for speed-dependent adhesion reduction due to
    creep force saturation at the contact patch. This is physically more
    accurate than a constant mu, especially at high speeds.

    Reference: O. Polach, "Creep forces in simulations of traction vehicles
    running on adhesion limit", Wear 258 (2005) 992-1000.

    Parameters:
      speed_kmh:          Current train speed
      vibration_rms:      Bogie vibration (proxy for rail roughness / wetness)
      humidity_pct:       Relative humidity (affects water film)
      leaf_contamination: Whether leaf mulch is present on rail

    Returns:
      mu: Available adhesion coefficient [0.02, 0.40]
    """
    v_ms = max(speed_kmh / 3.6, 0.1)  # avoid division by zero

    # Polach model parameters
    # ka, ks: adhesion reduction factors (empirical)
    # ka = adhesion parameter for dry/wet/contaminated
    # ks = speed-dependent saturation
    if leaf_contamination:
        # Leaf mulch: catastrophic adhesion loss (known railway safety issue)
        ka = 0.05
        ks = 0.40
        mu_0 = 0.08  # base adhesion with leaf film
    elif vibration_rms > 3.0:
        # Severe contamination / very wet
        ka = 0.15
        ks = 0.30
        mu_0 = 0.12
    elif vibration_rms > 2.0 or humidity_pct > 85:
        # Wet rail
        ka = 0.20
        ks = 0.25
        mu_0 = 0.18
    elif humidity_pct > 70:
        # Damp
        ka = 0.25
        ks = 0.20
        mu_0 = 0.25
    else:
        # Dry rail
        ka = 0.30
        ks = 0.15
        mu_0 = 0.35

    # Speed-dependent adhesion reduction (Polach characteristic)
    # mu(v) = mu_0 * (1 - ka * (1 - exp(-v/v_ref)))
    v_ref = 25.0  # reference speed (m/s) for saturation
    speed_factor = 1.0 - ks * (1.0 - math.exp(-v_ms / v_ref))

    # Vibration-induced micro-slip reduction
    vibration_penalty = max(0.0, 1.0 - 0.03 * max(0, vibration_rms - 1.0))

    mu = mu_0 * speed_factor * vibration_penalty

    # Clamp to physical bounds
    return max(0.02, min(0.40, mu))


# ── Davis Equation: Train Running Resistance (Task 11.3) ──────────────────────
def davis_resistance_N_per_tonne(speed_kmh: float, train: TrainConfig) -> float:
    """Compute specific running resistance using modified Davis equation.

    Indian Railways uses the RDSO modified Davis formula:
      R = A + B*V + C*V^2   (N/tonne)

    where:
      A = journal/bearing resistance (speed-independent)
      B = flange/rail friction (linear with speed)
      C = aerodynamic drag (quadratic with speed)

    For modern roller-bearing stock on BG track:
      A ~ 1.5 N/tonne
      B ~ 0.0075 N/tonne per km/h
      C ~ 0.00014 * (frontal_area / mass_per_unit_length)
    """
    v = speed_kmh
    mass_per_m = train.mass_tonnes / max(train.length_m, 1.0)  # t/m

    A = 1.5   # bearing resistance
    B = 0.0075
    C = 0.00014 * (train.frontal_area_m2 / mass_per_m)

    return A + B * v + C * v * v


def aerodynamic_drag_force_N(speed_kmh: float, train: TrainConfig) -> float:
    """Pure aerodynamic drag force: F = 0.5 * rho * Cd * A * v^2."""
    v_ms = speed_kmh / 3.6
    return 0.5 * RHO_AIR * train.drag_coeff * train.frontal_area_m2 * v_ms * v_ms


# ── Track Gradient and Curvature Resistance ───────────────────────────────────
_GRADIENT_CACHE: dict[tuple[float, float], float] = {}
_CURVATURE_CACHE: dict[tuple[float, float], float] = {}


def lookup_track_gradient(lat: float, lon: float) -> float:
    """GPS coordinate -> track gradient angle theta (radians).
    
    Positive = uphill (assists braking), negative = downhill (opposes braking).
    In production: reads from DEM (Digital Elevation Model) + track geometry DB.
    """
    key = (round(lat, 4), round(lon, 4))
    return _GRADIENT_CACHE.get(key, 0.0)


def lookup_track_curvature(lat: float, lon: float) -> float:
    """GPS coordinate -> track curvature radius (metres). 0 = straight.
    
    Used to compute curve resistance and cant deficiency effects.
    """
    key = (round(lat, 4), round(lon, 4))
    return _CURVATURE_CACHE.get(key, 0.0)  # 0 = straight track


def curve_resistance_N_per_tonne(curve_radius_m: float) -> float:
    """Curve resistance using RDSO formula for BG track.
    
    R_curve = 700 / R  (N/tonne) for R in metres
    Only applies if R > 0 (curved track).
    """
    if curve_radius_m <= 0:
        return 0.0
    return 700.0 / curve_radius_m


# ── Brake Fade Model ──────────────────────────────────────────────────────────
def brake_fade_factor(speed_kmh: float, braking_duration_s: float,
                      ambient_temp_c: float = 35.0) -> float:
    """Compute brake fade factor (1.0 = no fade, <1.0 = reduced effectiveness).
    
    Brake pads lose friction at elevated temperatures. Indian conditions
    (ambient 35-50C) accelerate fade onset.
    
    Model: exponential degradation based on energy dissipated.
    fade = 1 - alpha * (1 - exp(-E / E_ref))
    
    where E = energy dissipated during braking, E_ref = pad thermal capacity.
    """
    if braking_duration_s <= 0:
        return 1.0

    # Energy proxy: proportional to speed^2 * duration
    v_ms = speed_kmh / 3.6
    energy_proxy = v_ms * v_ms * braking_duration_s

    # Fade parameters (empirical for composition brake blocks)
    e_ref = 50000.0   # thermal reference (higher = more fade-resistant)
    alpha = 0.15      # max fade at full thermal saturation

    # Ambient temperature penalty (fade worsens in Indian summer)
    temp_factor = 1.0 + max(0.0, (ambient_temp_c - 30.0)) * 0.005

    fade = 1.0 - alpha * temp_factor * (1.0 - math.exp(-energy_proxy / e_ref))
    return max(0.5, min(1.0, fade))  # never below 50% effectiveness


# ── Advanced Multi-Phase Braking Distance Computation ─────────────────────────
def compute_braking_distance(
    speed_kmh: float,
    mu: float,
    theta_rad: float,
    train: TrainConfig,
    curve_radius_m: float = 0.0,
    headwind_kmh: float = 0.0,
    ambient_temp_c: float = 35.0,
) -> dict:
    """Compute total braking distance using multi-phase physics model.

    Phases:
      Phase 0: Reaction distance (driver perceives and initiates brake)
      Phase 1: Propagation distance (brake pipe pressure builds to full)
      Phase 2: Service braking (controlled deceleration)
      Phase 3: Final stop (low-speed regime, different adhesion behavior)

    The model integrates deceleration numerically in 0.1s steps, accounting for:
      - Speed-dependent adhesion (Polach)
      - Speed-dependent aerodynamic drag (Davis)
      - Gradient force (gravitational component)
      - Curve resistance
      - Rotational inertia (effective mass increase)
      - Brake fade (thermal)
    """
    v_ms = speed_kmh / 3.6
    if v_ms <= 0:
        return {"total_m": 0.0, "phases": {}, "decel_profile": []}

    mass_kg = train.mass_tonnes * 1000.0
    dt = 0.1  # integration time step (seconds)

    # ── Phase 0: Reaction distance ────────────────────────────────────────────
    d_reaction = v_ms * train.reaction_time_s

    # ── Phase 1: Propagation distance ─────────────────────────────────────────
    # During propagation, brakes are partially applied (linear ramp-up)
    d_propagation = 0.0
    v = v_ms
    t_prop = 0.0
    while t_prop < train.propagation_time_s and v > 0:
        # Partial braking (linear ramp from 0 to full)
        ramp = t_prop / max(train.propagation_time_s, 0.1)
        a_brake = _instantaneous_deceleration(
            v, mu * ramp, theta_rad, train, curve_radius_m, headwind_kmh, 0.0
        )
        v = max(0.0, v - a_brake * dt)
        d_propagation += v * dt
        t_prop += dt

    # ── Phase 2+3: Full braking (numerical integration) ──────────────────────
    d_braking = 0.0
    t_brake = 0.0
    decel_profile = []
    peak_decel = 0.0

    while v > 0.01:  # stop condition: < 0.036 km/h
        # Brake fade increases with duration
        fade = brake_fade_factor(v * 3.6, t_brake, ambient_temp_c)
        effective_mu = mu * fade

        # Speed-dependent adhesion adjustment (low-speed adhesion recovery)
        if v < 5.0:  # below 18 km/h, adhesion recovers slightly
            effective_mu *= 1.0 + 0.05 * (5.0 - v) / 5.0

        a_total = _instantaneous_deceleration(
            v, effective_mu, theta_rad, train, curve_radius_m, headwind_kmh, t_brake
        )
        peak_decel = max(peak_decel, a_total)

        v = max(0.0, v - a_total * dt)
        d_braking += v * dt
        t_brake += dt

        # Record deceleration profile (every 0.5s)
        if int(t_brake * 10) % 5 == 0:
            decel_profile.append({
                "t_s": round(t_brake, 1),
                "v_kmh": round(v * 3.6, 1),
                "a_ms2": round(a_total, 3),
                "d_m": round(d_braking, 1),
                "fade": round(fade, 3),
            })

        # Safety: prevent infinite loop
        if t_brake > 300:  # 5 min max braking time
            break

    total_distance = d_reaction + d_propagation + d_braking
    total_time = train.reaction_time_s + train.propagation_time_s + t_brake

    return {
        "total_m": total_distance,
        "reaction_m": d_reaction,
        "propagation_m": d_propagation,
        "braking_m": d_braking,
        "total_time_s": total_time,
        "peak_decel_ms2": peak_decel,
        "final_fade": brake_fade_factor(speed_kmh, t_brake, ambient_temp_c),
        "decel_profile": decel_profile,
    }


def _instantaneous_deceleration(
    v_ms: float, mu: float, theta_rad: float,
    train: TrainConfig, curve_radius_m: float,
    headwind_kmh: float, t_brake: float,
) -> float:
    """Compute instantaneous deceleration at given speed.

    a = (F_brake + F_drag + F_gradient + F_curve) / (m * lambda)

    where lambda = rotational inertia factor (>1, accounts for spinning masses).
    """
    mass_kg = train.mass_tonnes * 1000.0
    v_kmh = v_ms * 3.6

    # Braking force: F = mu * m * g * cos(theta) * (brake_weight_pct / 100)
    # brake_weight_pct accounts for actual braked axles vs total weight
    f_brake = mu * mass_kg * g * math.cos(theta_rad) * (train.brake_weight_pct / 100.0)

    # Aerodynamic drag (assists braking): Davis + explicit drag
    # Include headwind effect
    effective_speed_kmh = v_kmh + headwind_kmh
    f_aero = aerodynamic_drag_force_N(effective_speed_kmh, train)

    # Running resistance (wheel/bearing friction — always assists stopping)
    f_resistance = davis_resistance_N_per_tonne(v_kmh, train) * train.mass_tonnes

    # Gravitational component along track
    # Positive theta = uphill = assists braking
    f_gravity = mass_kg * g * math.sin(theta_rad)

    # Curve resistance (always opposes motion, assists braking)
    f_curve = curve_resistance_N_per_tonne(curve_radius_m) * train.mass_tonnes

    # Total decelerating force
    f_total = f_brake + f_aero + f_resistance + f_gravity + f_curve

    # Effective mass (rotational inertia increases effective mass)
    effective_mass = mass_kg * train.rotational_inertia

    # Deceleration (m/s^2)
    a = f_total / effective_mass

    # Cap at physical maximum (wheel-slide protection limits deceleration to mu*g)
    a_max = mu * g
    return min(a, a_max)


# ── Adhesion Estimation (wrapper combining Polach + sensor data) ──────────────
def estimate_adhesion(vibration_rms: float, speed_kmh: float,
                      humidity_pct: float = 50.0) -> float:
    """Estimate adhesion using Polach model with sensor fusion.
    
    In production: 1D-CNN on vibration time series + environmental data.
    Current: Polach analytical model with vibration/humidity inputs.
    """
    leaf_contamination = vibration_rms > 4.0  # extreme vibration hints at debris
    return polach_adhesion(speed_kmh, vibration_rms, humidity_pct, leaf_contamination)


# ── Certified Kavach 4.0 Distance (conservative baseline) ────────────────────
@lru_cache(maxsize=256)
def kavach_certified_stopping_distance(speed_kmh: float) -> float:
    """Conservative certified Kavach 4.0 stopping distance.

    Uses worst-case assumptions:
      - mu = 0.08 (leaf-contaminated rail)
      - Flat track (theta = 0)
      - Maximum reaction + propagation time
      - No aerodynamic assistance
      - Heaviest train configuration

    Real implementation reads certified curves from Kavach 4.0 data bus.
    """
    v_ms = speed_kmh / 3.6
    worst_mu = 0.08
    worst_train = TrainConfig(
        mass_tonnes=1400, brake_weight_pct=70, rotational_inertia=1.04,
        reaction_time_s=3.0, propagation_time_s=7.0,
        emergency_decel_max=0.7,
    )
    # Simple energy formula for certified (no beneficial forces counted)
    d_reaction = v_ms * worst_train.reaction_time_s
    d_propagation = v_ms * worst_train.propagation_time_s * 0.9  # slight decel during prop
    # Pure kinetic energy dissipation
    effective_mass_factor = worst_train.rotational_inertia
    d_brake = (v_ms ** 2 * effective_mass_factor) / (
        2 * worst_mu * g * (worst_train.brake_weight_pct / 100.0)
    )
    return d_reaction + d_propagation + d_brake


# ── Main Advisory Computation ─────────────────────────────────────────────────
def compute_advisory(
    speed_kmh: float,
    lat: float,
    lon: float,
    vibration_rms: Optional[float],
    humidity_pct: float = 50.0,
    headwind_kmh: float = 0.0,
    ambient_temp_c: float = 35.0,
    train_type: str = "default",
) -> Optional[dict]:
    """Compute Kavach++ advisory braking curve using advanced physics.

    Returns None (KAVACH_ADVISORY_UNAVAILABLE) if required sensor data absent.
    Ensures advisory_distance >= certified_distance (safety invariant Req 10 C3).
    """
    import time as _time
    t0 = _time.perf_counter()

    if vibration_rms is None:
        unavailable_counter.inc()
        return None

    # Select train configuration
    train = TRAIN_CONFIGS.get(train_type, _active_train)

    # Compute adhesion using Polach model
    mu = estimate_adhesion(vibration_rms, speed_kmh, humidity_pct)

    # Look up track geometry
    theta = lookup_track_gradient(lat, lon)
    curve_radius = lookup_track_curvature(lat, lon)

    # Compute full braking distance with multi-phase model
    braking = compute_braking_distance(
        speed_kmh=speed_kmh,
        mu=mu,
        theta_rad=theta,
        train=train,
        curve_radius_m=curve_radius,
        headwind_kmh=headwind_kmh,
        ambient_temp_c=ambient_temp_c,
    )

    adv_dist = braking["total_m"]
    cert_dist = kavach_certified_stopping_distance(speed_kmh)

    # Safety invariant: advisory must be >= certified (Req 10 C3)
    clamped = False
    if adv_dist < cert_dist:
        adv_dist = cert_dist
        clamped = True

    elapsed_ms = (_time.perf_counter() - t0) * 1000
    braking_latency.observe(elapsed_ms)

    return {
        "alertType":              "KAVACH_ADVISORY",
        "label":                  "ADVISORY -- NOT CERTIFIED",
        "advisoryStoppingDist_m": round(adv_dist, 2),
        "certifiedStoppingDist_m": round(cert_dist, 2),
        "speedKmh":               speed_kmh,
        "adhesionCoeff":          round(mu, 4),
        "gradientRad":            round(theta, 5),
        "curveRadiusM":           curve_radius,
        "trainType":              train_type,
        "brakingPhases": {
            "reactionDist_m":     round(braking["reaction_m"], 1),
            "propagationDist_m":  round(braking["propagation_m"], 1),
            "brakingDist_m":      round(braking["braking_m"], 1),
            "totalTime_s":        round(braking["total_time_s"], 1),
            "peakDecel_ms2":      round(braking["peak_decel_ms2"], 3),
            "brakeFade":          round(braking["final_fade"], 3),
        },
        "safetyInvariant": {
            "satisfied":          adv_dist >= cert_dist,
            "clamped":            clamped,
            "marginPct":          round((adv_dist - cert_dist) / max(cert_dist, 1) * 100, 1),
        },
        "environment": {
            "humidityPct":        humidity_pct,
            "headwindKmh":        headwind_kmh,
            "ambientTempC":       ambient_temp_c,
        },
        "computeLatencyMs":       round(elapsed_ms, 2),
        "timestamp_utc":          datetime.now(timezone.utc).isoformat(),
        "alertId":                str(uuid.uuid4()),
    }


# ── FastAPI service ────────────────────────────────────────────────────────────
app = FastAPI(title="RailOS Kavach++ Advisory", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class KavachRequest(BaseModel):
    speed_kmh:          float
    lat:                float
    lon:                float
    vibration_rms:      Optional[float] = None
    humidity_pct:       float = 50.0
    headwind_kmh:       float = 0.0
    ambient_temp_c:     float = 35.0
    train_type:         str = "default"


@app.on_event("startup")
def _startup() -> None:
    start_http_server(METRICS_PORT)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/kavach-advisory")
def get_advisory(req: KavachRequest) -> dict:
    result = compute_advisory(
        req.speed_kmh, req.lat, req.lon, req.vibration_rms,
        humidity_pct=req.humidity_pct, headwind_kmh=req.headwind_kmh,
        ambient_temp_c=req.ambient_temp_c, train_type=req.train_type,
    )
    if result is None:
        return {"status": "KAVACH_ADVISORY_UNAVAILABLE"}
    advisories_emitted.inc()
    _publish(ADVISORY_TOPIC, result)
    return result


def _publish(topic: str, payload: dict) -> None:
    """Publish to Kafka using cached producer — no per-request connection overhead."""
    producer = _get_producer()
    if producer is None:
        return
    try:
        producer.send(topic, value=json.dumps(payload).encode())
        # Don't flush synchronously — linger_ms handles batching
    except Exception as exc:
        log.error("Kafka publish failed: %s", exc)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
