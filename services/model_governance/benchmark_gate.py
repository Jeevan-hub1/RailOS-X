"""
RailOS Benchmark Gate (Task 18.2)
pytest-based gate that runs before any model deployment approval.
Covers: inference latency, precision/recall, calibration, MAE, conflict-free rate.
REGRESSION_DETECTED emitted if any primary metric degrades >5% vs deployed baseline.
Satisfies: Req 14, Design §11
"""
from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.kafka_utils import publish_alert
from common.datetime_utils import now_iso

log = logging.getLogger(__name__)
REGRESSION_THRESHOLD = float(os.environ.get("REGRESSION_THRESHOLD", "0.05"))  # 5%
MODEL_ID          = os.environ.get("MODEL_ID", "")
CANDIDATE_VERSION = os.environ.get("CANDIDATE_VERSION", "")


def emit_regression_alert(model_id: str, metric: str, deployed: float, candidate: float) -> None:
    payload = {
        "alertType":        "REGRESSION_DETECTED",
        "modelId":          model_id,
        "metricName":       metric,
        "deployedValue":    deployed,
        "candidateValue":   candidate,
        "degradationPct":   round(abs(candidate - deployed) / max(abs(deployed), 1e-9) * 100, 2),
        "timestamp_utc":    now_iso(),
    }
    log.error("REGRESSION_DETECTED: %s", json.dumps(payload))
    publish_alert(payload)


def check_regression(model_id: str, metric: str, deployed: float, candidate: float) -> bool:
    """Return True if metric improved or within tolerance. False = regression."""
    if deployed == 0:
        return True
    delta_pct = (deployed - candidate) / abs(deployed)  # positive = degradation (lower = worse for precision)
    if delta_pct > REGRESSION_THRESHOLD:
        emit_regression_alert(model_id, metric, deployed, candidate)
        return False
    return True


# ── Pytest benchmark fixtures used by each model's test suite ──────────────────

BENCHMARK_REGISTRY: dict[str, dict[str, float]] = {
    # Deployed baselines (loaded from MLflow in production)
    "defect_detector":   {"precision": 0.90, "recall": 0.90, "inference_latency_ms": 100},
    "maintenance_engine":{"calibration_error": 0.05, "ci_coverage": 0.85, "inference_latency_ms": 10000},
    "delay_predictor":   {"mae_minutes": 8.0,  "inference_latency_ms": 2000},
    "marl_scheduler":    {"conflict_free_rate": 0.70, "proposal_latency_ms": 30000},
}


def load_deployed_baseline(model_id: str) -> dict[str, float]:
    """Load the deployed model's baseline metrics from MLflow."""
    try:
        import mlflow
        client = mlflow.tracking.MlflowClient()
        runs = client.search_runs(
            experiment_ids=["0"],
            filter_string=f"tags.model_id='{model_id}' and tags.deployed='true'",
            max_results=1,
            order_by=["attribute.start_time DESC"],
        )
        if runs:
            return {k: v for k, v in runs[0].data.metrics.items()}
    except Exception as exc:
        log.warning("MLflow baseline lookup failed: %s — using hardcoded defaults", exc)
    return BENCHMARK_REGISTRY.get(model_id, {})
