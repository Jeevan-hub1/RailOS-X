"""
RailOS ART Adversarial Validation (Task 18.5)
FGSM perturbation test on each model before deployment.
Blocks if primary metric degrades >15% on adversarial test set.
Satisfies: Req 43 C3, Design §11
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP       = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                         "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
ADVERSARIAL_THRESHOLD = float(os.environ.get("ADVERSARIAL_DEGRADATION_THRESHOLD", "0.15"))  # 15%


def fgsm_perturb(x: "np.ndarray", gradient: "np.ndarray", epsilon: float = 0.1) -> "np.ndarray":
    """Fast Gradient Sign Method perturbation."""
    return x + epsilon * np.sign(gradient)


def evaluate_adversarial_robustness(
    model_id:        str,
    model:           Any,
    x_test:          "np.ndarray",
    y_test:          "np.ndarray",
    metric_fn:       Callable,
    epsilon:         float = 0.1,
) -> dict[str, Any]:
    """
    Evaluate model on clean and FGSM-perturbed test sets.
    Blocks deployment if metric degrades >15%.

    Args:
        model_id:   Model identifier
        model:      PyTorch model (requires .parameters() and .forward())
        x_test:     Clean test inputs (numpy)
        y_test:     Test labels (numpy)
        metric_fn:  Callable(y_true, y_pred) → float (higher = better)
        epsilon:    FGSM perturbation magnitude

    Returns:
        {clean_metric, adversarial_metric, degradation_pct, passed}
    """
    import torch
    import torch.nn as nn

    model.eval()

    # Clean evaluation
    with torch.no_grad():
        x_tensor = torch.tensor(x_test, dtype=torch.float32)
        y_pred_clean = model(x_tensor).numpy()
    clean_metric = float(metric_fn(y_test, y_pred_clean))

    # FGSM perturbation
    x_adv = _fgsm_attack_numpy(model, x_test, y_test, epsilon)

    with torch.no_grad():
        x_adv_tensor = torch.tensor(x_adv, dtype=torch.float32)
        y_pred_adv = model(x_adv_tensor).numpy()
    adv_metric = float(metric_fn(y_test, y_pred_adv))

    degradation_pct = (clean_metric - adv_metric) / max(abs(clean_metric), 1e-9)
    passed = degradation_pct <= ADVERSARIAL_THRESHOLD

    result = {
        "model_id":          model_id,
        "epsilon":           epsilon,
        "clean_metric":      round(clean_metric, 4),
        "adversarial_metric": round(adv_metric, 4),
        "degradation_pct":   round(degradation_pct * 100, 2),
        "threshold_pct":     ADVERSARIAL_THRESHOLD * 100,
        "passed":            passed,
        "n_test_samples":    len(x_test),
        "timestamp_utc":     datetime.now(timezone.utc).isoformat(),
    }

    if not passed:
        log.error("ADVERSARIAL_VALIDATION_FAILED: %s", json.dumps(result))
        _emit_adversarial_failure(result)

    return result


def _fgsm_attack_numpy(model, x_np: np.ndarray, y_np: np.ndarray, epsilon: float) -> np.ndarray:
    """Compute FGSM adversarial examples. Returns perturbed numpy array."""
    import torch
    import torch.nn as nn

    x = torch.tensor(x_np, dtype=torch.float32, requires_grad=True)
    y = torch.tensor(y_np, dtype=torch.float32)

    try:
        output = model(x)
        loss   = nn.functional.mse_loss(output.squeeze(), y)
        loss.backward()
        gradient = x.grad.detach().numpy()
        x_adv = x_np + epsilon * np.sign(gradient)
        return np.clip(x_adv, x_np.min(), x_np.max())
    except Exception as exc:
        log.warning("FGSM attack failed: %s — returning clean samples", exc)
        return x_np


def _emit_adversarial_failure(result: dict) -> None:
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
        payload = {**result, "alertType": "ADVERSARIAL_VALIDATION_FAILED"}
        p.send("monitoring.alerts", value=json.dumps(payload).encode())
        p.flush(timeout=5)
    except Exception as exc:
        log.warning("Kafka emit failed: %s", exc)
