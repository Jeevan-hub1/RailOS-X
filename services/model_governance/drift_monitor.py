"""
RailOS Evidently AI Model Drift Monitor (Task 18.4)
Daily PSI rolling window per deployed model.
MODEL_DRIFT_ALERT + DRIFT_WARNING on outputs after 3 consecutive PSI ≥ 0.2.
Satisfies: Req 20, Design §11
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import defaultdict
from typing import Any

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.kafka_utils import publish_alert
from common.datetime_utils import now_iso

log = logging.getLogger(__name__)
PSI_THRESHOLD     = float(os.environ.get("PSI_DRIFT_CRITICAL_THRESHOLD", "0.2"))
CONSECUTIVE_DAYS  = int(os.environ.get("DRIFT_CONSECUTIVE_DAYS", "3"))

# Track consecutive drift violations per model
_violation_counts: dict[str, int] = defaultdict(int)
_drift_active:     dict[str, bool] = defaultdict(bool)


def compute_psi(baseline: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index between baseline and current distributions."""
    baseline = np.asarray(baseline, dtype=float)
    current  = np.asarray(current,  dtype=float)

    # Build common bin edges from combined data
    combined = np.concatenate([baseline, current])
    edges = np.percentile(combined, np.linspace(0, 100, bins + 1))
    edges[0]  -= 1e-9
    edges[-1] += 1e-9

    b_hist = np.histogram(baseline, bins=edges)[0]
    c_hist = np.histogram(current,  bins=edges)[0]

    # Normalize to proportions, avoid zero
    b_pct = np.where(b_hist == 0, 1e-4, b_hist / len(baseline))
    c_pct = np.where(c_hist == 0, 1e-4, c_hist / len(current))

    psi = float(np.sum((c_pct - b_pct) * np.log(c_pct / b_pct)))
    return round(psi, 6)


def check_drift(model_id: str, psi_score: float) -> dict[str, Any]:
    """
    Check drift score for a model. Emit MODEL_DRIFT_ALERT after 3 consecutive violations.

    Returns: {model_id, psi_score, drift_warning, consecutive_violations, alert_emitted}
    """
    is_violation = psi_score >= PSI_THRESHOLD

    if is_violation:
        _violation_counts[model_id] += 1
    else:
        _violation_counts[model_id] = 0
        if _drift_active[model_id]:
            _drift_active[model_id] = False
            log.info("Drift cleared for model %s (PSI=%.4f)", model_id, psi_score)

    alert_emitted = False
    if _violation_counts[model_id] >= CONSECUTIVE_DAYS and not _drift_active[model_id]:
        _drift_active[model_id] = True
        alert_emitted = True
        _emit_drift_alert(model_id, psi_score, _violation_counts[model_id])

    return {
        "model_id":              model_id,
        "psi_score":             psi_score,
        "threshold":             PSI_THRESHOLD,
        "drift_warning":         _drift_active[model_id],
        "consecutive_violations": _violation_counts[model_id],
        "alert_emitted":         alert_emitted,
    }


def is_drift_active(model_id: str) -> bool:
    """Check if DRIFT_WARNING is active for a model (used to flag advisory outputs)."""
    return _drift_active.get(model_id, False)


def _emit_drift_alert(model_id: str, psi_score: float, consecutive: int) -> None:
    payload = {
        "alertType":           "MODEL_DRIFT_ALERT",
        "modelId":             model_id,
        "psiScore":            psi_score,
        "consecutiveDays":     consecutive,
        "threshold":           PSI_THRESHOLD,
        "timestamp_utc":       now_iso(),
    }
    log.warning("MODEL_DRIFT_ALERT: %s", json.dumps(payload))
    publish_alert(payload)
