"""
RailOS Predictive Maintenance — Inference Service (Tasks 7.6–7.7)

FastAPI + Kafka consumer service:
  - Subscribes to `train.features.maintenance`
  - Calls ConformalMaintenanceWrapper.predict() for each feature window
  - Publishes MAINTENANCE_ADVISORY or INSUFFICIENT_DATA to `maintenance.advisories`

Risk scoring (Design §6.2, Task 14.1–14.2):
  riskScore = failureProbability × severity_weight  (HIGH=3 for maintenance), capped 4.0
  riskTier:  1 ≥ 3.2  (dual-auth),  2 → 2.0–3.19 (single-auth),  3 < 2.0 (standard)

Satisfies: Req 4 C1, C2, C3, C6; Design §6.2
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import torch
from fastapi import FastAPI
from prometheus_client import Counter, Histogram, start_http_server

# ---------------------------------------------------------------------------
# Internal imports (package-relative)
# ---------------------------------------------------------------------------
import sys

_HERE = os.path.dirname(__file__)
_ENGINE_ROOT = os.path.dirname(_HERE)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from model.lstm_model import MaintenanceLSTM
from model.conformal_wrapper import ConformalMaintenanceWrapper
from service.shap_attribution import compute_shap_top3

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# ---------------------------------------------------------------------------
# Configuration (from environment / ConfigMap)
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
FAILURE_THRESHOLD: float     = float(os.getenv("FAILURE_THRESHOLD", "0.80"))
MODEL_VERSION: str            = os.getenv("MODEL_VERSION", "1.0.0")
MODEL_PATH: Optional[str]     = os.getenv("MODEL_PATH")
FEATURES_TOPIC: str           = "train.features.maintenance"
ADVISORIES_TOPIC: str         = "maintenance.advisories"
PROMETHEUS_PORT: int          = int(os.getenv("PROMETHEUS_PORT", "9090"))

# Risk scoring constants (Design §6.2, Task 14.1)
SEVERITY_WEIGHT_HIGH: float = 3.0   # Maintenance advisory is severity HIGH
RISK_SCORE_CAP: float       = 4.0

# Horizon hours published in every maintenance advisory (Req 4)
HORIZON_HOURS: int = 72

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
ADVISORIES_EMITTED = Counter(
    "railos_maintenance_advisories_total",
    "Total MAINTENANCE_ADVISORY events emitted",
    ["risk_tier"],
)
INSUFFICIENT_DATA_EMITTED = Counter(
    "railos_maintenance_insufficient_data_total",
    "Total INSUFFICIENT_DATA advisories emitted",
)
INFERENCE_LATENCY = Histogram(
    "railos_maintenance_inference_latency_seconds",
    "End-to-end inference + advisory publish latency",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


# ---------------------------------------------------------------------------
# Risk scoring helpers (Task 14.1–14.2)
# ---------------------------------------------------------------------------
def compute_risk_score(failure_probability: float, severity_weight: float = SEVERITY_WEIGHT_HIGH) -> float:
    """riskScore = failure_probability × severity_weight, capped at 4.0."""
    return min(failure_probability * severity_weight, RISK_SCORE_CAP)


def compute_risk_tier(risk_score: float) -> int:
    """
    Tier 1: riskScore ≥ 3.2  (dual-auth)
    Tier 2: 2.0 ≤ riskScore < 3.2  (single-auth)
    Tier 3: riskScore < 2.0  (standard)
    """
    if risk_score >= 3.2:
        return 1
    if risk_score >= 2.0:
        return 2
    return 3


# ---------------------------------------------------------------------------
# Maintenance service class
# ---------------------------------------------------------------------------
class MaintenanceService:
    """Orchestrates inference, advisory creation, and Kafka I/O."""

    def __init__(self) -> None:
        self._model: Optional[MaintenanceLSTM] = None
        self._wrapper: Optional[ConformalMaintenanceWrapper] = None
        self._producer: Any = None   # kafka.KafkaProducer (optional dep)
        self._consumer: Any = None   # kafka.KafkaConsumer (optional dep)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def startup(self) -> None:
        """Load model weights and initialise Kafka client."""
        self._model = MaintenanceLSTM()
        if MODEL_PATH and os.path.isfile(MODEL_PATH):
            state = torch.load(MODEL_PATH, map_location="cpu", weights_only=True)
            self._model.load_state_dict(state)
            log.info("Loaded model weights from %s", MODEL_PATH)
        else:
            log.warning(
                "MODEL_PATH not set or file not found ('%s'); using untrained model weights.",
                MODEL_PATH,
            )
        self._model.eval()

        # Build a small calibration residual array (constant 0.15) as default
        # when no pre-computed residuals are available.
        default_residuals = np.full(200, 0.15, dtype=np.float32)
        self._wrapper = ConformalMaintenanceWrapper(
            lstm_model=self._model,
            calibration_residuals=default_residuals,
        )

        self._setup_kafka()
        log.info("MaintenanceService started. threshold=%.2f version=%s", FAILURE_THRESHOLD, MODEL_VERSION)

    def _setup_kafka(self) -> None:
        """Initialise KafkaProducer and KafkaConsumer (graceful if unavailable)."""
        try:
            from kafka import KafkaConsumer, KafkaProducer  # type: ignore[import]

            self._producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=5,
            )
            self._consumer = KafkaConsumer(
                FEATURES_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
                group_id="maintenance-engine",
                auto_offset_reset="latest",
                enable_auto_commit=True,
            )
            log.info("Kafka connected to %s", KAFKA_BOOTSTRAP_SERVERS)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Kafka unavailable (%s). Running without message bus (test / dev mode).", exc
            )

    def shutdown(self) -> None:
        """Graceful shutdown of Kafka clients."""
        if self._consumer:
            try:
                self._consumer.close()
            except Exception:  # noqa: BLE001
                pass
        if self._producer:
            try:
                self._producer.flush(timeout=5)
                self._producer.close()
            except Exception:  # noqa: BLE001
                pass
        log.info("MaintenanceService shut down.")

    # ------------------------------------------------------------------
    # Core inference pipeline
    # ------------------------------------------------------------------
    def process_feature_window(self, window_payload: dict) -> dict:
        """Process one feature window and return the advisory dict (or None).

        Args:
            window_payload: {asset_id, features: [[f×8]×1800], interpolation_pct, timestamp_utc}

        Returns:
            Advisory dict (MAINTENANCE_ADVISORY or INSUFFICIENT_DATA), or {} if below threshold.
        """
        import time
        t0 = time.monotonic()

        asset_id: str        = window_payload["asset_id"]
        features: list       = window_payload["features"]
        interp_pct: float    = float(window_payload.get("interpolation_pct", 0.0))
        timestamp_utc: str   = window_payload.get("timestamp_utc", _now_iso())

        # Build tensor (1, 1800, 8)
        tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0)  # (1, seq, 8)

        prediction = self._wrapper.predict(tensor, interpolation_pct=interp_pct)

        latency = time.monotonic() - t0
        INFERENCE_LATENCY.observe(latency)

        # ------------------------------------------------------------------
        # Path A — insufficient data
        # ------------------------------------------------------------------
        if prediction.insufficient_data:
            advisory = self._build_insufficient_data_advisory(
                asset_id=asset_id,
                interpolation_pct=interp_pct,
                timestamp_utc=timestamp_utc,
            )
            self._publish(advisory)
            INSUFFICIENT_DATA_EMITTED.inc()
            log.warning("INSUFFICIENT_DATA for asset %s (interp=%.1f%%)", asset_id, interp_pct)
            return advisory

        # ------------------------------------------------------------------
        # Path B — below threshold: no advisory, no publish
        # ------------------------------------------------------------------
        if prediction.failure_probability <= FAILURE_THRESHOLD:
            log.debug(
                "Below threshold for asset %s: prob=%.4f", asset_id, prediction.failure_probability
            )
            return {}

        # ------------------------------------------------------------------
        # Path C — advisory required
        # ------------------------------------------------------------------
        risk_score = compute_risk_score(prediction.failure_probability)
        risk_tier  = compute_risk_tier(risk_score)

        # SHAP attribution (top-3 features)
        try:
            top3 = compute_shap_top3(self._model, tensor)
        except Exception as exc:  # noqa: BLE001
            log.warning("SHAP attribution failed (%s); using empty attribution.", exc)
            top3 = []

        advisory = {
            "alertId":           str(uuid.uuid4()),
            "alertType":         "MAINTENANCE_ADVISORY",
            "timestamp_utc":     timestamp_utc,
            "assetId":           asset_id,
            "failureProbability": round(prediction.failure_probability, 4),
            "horizonHours":      HORIZON_HOURS,
            "ciLower":           prediction.ci_lower,
            "ciUpper":           prediction.ci_upper,
            "dataQualityPct":    round(prediction.data_quality_pct, 2),
            "attribution":       {"top3Features": top3},
            "modelVersion":      MODEL_VERSION,
            "driftWarning":      False,
            "riskScore":         round(risk_score, 4),
            "riskTier":          risk_tier,
        }

        self._publish(advisory)
        ADVISORIES_EMITTED.labels(risk_tier=str(risk_tier)).inc()
        log.info(
            "MAINTENANCE_ADVISORY emitted: asset=%s prob=%.4f riskTier=%d riskScore=%.4f",
            asset_id,
            prediction.failure_probability,
            risk_tier,
            risk_score,
        )
        return advisory

    # ------------------------------------------------------------------
    # Consumer loop
    # ------------------------------------------------------------------
    def run_consumer_loop(self) -> None:
        """Blocking Kafka consumer loop. Call from a background thread."""
        if self._consumer is None:
            log.error("Kafka consumer not initialised; cannot start consumer loop.")
            return
        log.info("Starting Kafka consumer loop on topic %s", FEATURES_TOPIC)
        for msg in self._consumer:
            try:
                self.process_feature_window(msg.value)
            except Exception as exc:  # noqa: BLE001
                log.exception("Error processing feature window: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _publish(self, advisory: dict) -> None:
        """Publish advisory dict to maintenance.advisories topic."""
        if self._producer is None:
            log.debug("No Kafka producer; skipping publish of %s", advisory.get("alertType"))
            return
        try:
            self._producer.send(ADVISORIES_TOPIC, value=advisory)
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to publish advisory to Kafka: %s", exc)

    @staticmethod
    def _build_insufficient_data_advisory(
        asset_id: str,
        interpolation_pct: float,
        timestamp_utc: str,
    ) -> dict:
        """Build an INSUFFICIENT_DATA advisory — no score field per spec."""
        return {
            "alertId":        str(uuid.uuid4()),
            "alertType":      "INSUFFICIENT_DATA",
            "timestamp_utc":  timestamp_utc,
            "assetId":        asset_id,
            "dataQualityPct": round(interpolation_pct, 2),
            "modelVersion":   MODEL_VERSION,
        }


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
_service = MaintenanceService()


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ANN001
    """FastAPI lifespan handler — startup and shutdown."""
    try:
        start_http_server(PROMETHEUS_PORT)
    except OSError:
        log.warning("Prometheus port %d already in use; skipping.", PROMETHEUS_PORT)

    _service.startup()

    import threading
    _t = threading.Thread(target=_service.run_consumer_loop, daemon=True)
    _t.start()

    yield

    _service.shutdown()


app = FastAPI(
    title="RailOS Maintenance Engine",
    version=MODEL_VERSION,
    description="Predictive Maintenance inference service (Req 4, Req 18)",
    lifespan=_lifespan,
)


@app.get("/health")
def health() -> dict:
    """Liveness probe endpoint."""
    return {"status": "ok", "modelVersion": MODEL_VERSION}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe — confirms model is loaded."""
    loaded = _service._model is not None
    return {"ready": loaded, "modelVersion": MODEL_VERSION}


@app.post("/infer", summary="Synchronous inference endpoint (testing / dev)")
def infer(window_payload: dict) -> dict:
    """
    Accept a feature window and return the advisory synchronously.
    This bypasses Kafka and is intended for integration tests and tooling.

    Body: {asset_id, features: [[f×8]×1800], interpolation_pct, timestamp_utc}
    """
    return _service.process_feature_window(window_payload)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "maintenance_service:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )
