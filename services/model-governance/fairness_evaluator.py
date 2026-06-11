"""
RailOS Fairlearn Fairness Evaluation (Task 18.3)
Partitions held-out dataset by 3 strata: weather, time-of-day, infrastructure region.
Blocks deployment if any stratum degrades >10% vs overall baseline.
Emits BIAS_THRESHOLD_EXCEEDED on violation.
Satisfies: Req 19, Design §11
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP   = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                    "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
BIAS_THRESHOLD    = float(os.environ.get("BIAS_THRESHOLD_PCT", "10.0"))


def evaluate_fairness(
    model_id: str,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    metadata: dict[str, np.ndarray],
    primary_metric_fn,
) -> dict[str, Any]:
    """
    Evaluate model fairness across 3 strata.

    Args:
        model_id:          Model identifier
        y_true:            Ground truth labels
        y_pred:            Model predictions
        metadata:          Dict with keys 'weather', 'time_of_day', 'region'
        primary_metric_fn: Callable(y_true, y_pred) → float (higher = better)

    Returns:
        {overall_metric, strata_results, passed, violations}
    """
    overall_metric = float(primary_metric_fn(y_true, y_pred))

    strata_results = {}
    violations = []

    # Strata definitions
    strata_definitions = {
        "weather":     ("weather",     ["clear", "rain", "fog"]),
        "time_of_day": ("time_of_day", ["day", "night"]),
        "region":      ("region",      None),  # unique values
    }

    for stratum_name, (meta_key, categories) in strata_definitions.items():
        if meta_key not in metadata:
            continue
        values = metadata[meta_key]
        cats = categories if categories else list(set(values))

        for cat in cats:
            mask = values == cat
            if not np.any(mask):
                continue
            stratum_metric = float(primary_metric_fn(y_true[mask], y_pred[mask]))
            degradation = (overall_metric - stratum_metric) / max(abs(overall_metric), 1e-9) * 100

            strata_results[f"{stratum_name}:{cat}"] = {
                "metric": round(stratum_metric, 4),
                "degradation_pct": round(degradation, 2),
                "n_samples": int(np.sum(mask)),
            }

            if degradation > BIAS_THRESHOLD:
                violations.append({
                    "stratum": f"{stratum_name}:{cat}",
                    "metric": round(stratum_metric, 4),
                    "baseline": round(overall_metric, 4),
                    "degradation_pct": round(degradation, 2),
                })

    passed = len(violations) == 0

    if not passed:
        _emit_bias_alert(model_id, violations, overall_metric)

    return {
        "model_id":       model_id,
        "overall_metric": round(overall_metric, 4),
        "strata_results": strata_results,
        "violations":     violations,
        "passed":         passed,
        "threshold_pct":  BIAS_THRESHOLD,
    }


def _emit_bias_alert(model_id: str, violations: list[dict], overall: float) -> None:
    payload = {
        "alertType":    "BIAS_THRESHOLD_EXCEEDED",
        "modelId":      model_id,
        "overallMetric": overall,
        "violations":   violations,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    log.error("BIAS_THRESHOLD_EXCEEDED: %s", json.dumps(payload))
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
        p.send("monitoring.alerts", value=json.dumps(payload).encode())
        p.flush(timeout=5)
    except Exception as exc:
        log.warning("Kafka emit failed: %s", exc)
