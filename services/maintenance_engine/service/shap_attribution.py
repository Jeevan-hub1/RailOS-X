"""
RailOS Predictive Maintenance — SHAP Attribution (Task 7.7)
Computes top-3 feature attribution for MAINTENANCE_ADVISORY events.

Uses shap.DeepExplainer when available; falls back to gradient-based approximation.
Maps raw feature indices to IR domain plain-language terminology.

Satisfies: Req 4 C5, Design §6.2
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import torch

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature index → IR domain terminology mapping (Design §6.2)
# ---------------------------------------------------------------------------
FEATURE_NAMES = [
    "vibration_rms",          # 0
    "vibration_kurtosis",     # 1
    "vibration_peak",         # 2
    "temperature_bogie",      # 3
    "wheel_load_left",        # 4
    "wheel_load_right",       # 5
    "acoustic_emission_rms",  # 6
    "speed_kmh",              # 7
]

IR_TERMINOLOGY: dict[str, str] = {
    "vibration_rms":         "vibration amplitude (RMS) on monitored bogie",
    "vibration_kurtosis":    "kurtosis spike indicating bearing defect",
    "vibration_peak":        "peak vibration amplitude",
    "temperature_bogie":     "elevated bogie bearing temperature",
    "wheel_load_left":       "abnormal left wheel load",
    "wheel_load_right":      "abnormal right wheel load",
    "acoustic_emission_rms": "acoustic emission from rail-wheel interface",
    "speed_kmh":             "train speed at time of measurement",
}


def _gradient_attribution(
    model: torch.nn.Module,
    input_tensor: torch.Tensor,
) -> np.ndarray:
    """Gradient × input attribution as a fast fallback when SHAP is unavailable.

    Computes ∂output/∂input × input, averaged over timesteps, yielding an
    8-element feature importance vector.

    Args:
        model: MaintenanceLSTM in eval mode.
        input_tensor: (1, seq_len, 8) float32 tensor.

    Returns:
        np.ndarray of shape (8,) — absolute per-feature importance scores.
    """
    model.eval()
    x = input_tensor.clone().detach().requires_grad_(True)
    output = model(x)
    output.backward()
    # Gradient × input: shape (1, seq_len, 8)
    grad_input = (x.grad * x).detach().cpu().numpy()
    # Average absolute value over batch and time dimensions → (8,)
    importance = np.abs(grad_input).mean(axis=(0, 1))
    return importance


def _shap_deep_attribution(
    model: torch.nn.Module,
    input_tensor: torch.Tensor,
) -> np.ndarray:
    """DeepExplainer-based SHAP attribution.

    Uses a zero-baseline background (shape equal to input_tensor).
    Returns absolute mean SHAP values per feature, averaged over timesteps.

    Args:
        model: MaintenanceLSTM in eval mode.
        input_tensor: (1, seq_len, 8) float32 tensor.

    Returns:
        np.ndarray of shape (8,) — absolute per-feature importance scores.
    """
    import shap  # imported lazily so the module is still usable without shap installed

    model.eval()
    background = torch.zeros_like(input_tensor)
    explainer = shap.DeepExplainer(model, background)
    # shap_values: list of arrays, one per output neuron; shape (1, seq_len, 8)
    shap_values = explainer.shap_values(input_tensor)
    if isinstance(shap_values, list):
        sv = np.array(shap_values[0])
    else:
        sv = np.array(shap_values)
    # Average absolute SHAP over batch and time → (8,)
    return np.abs(sv).mean(axis=(0, 1))


def compute_shap_top3(
    model: torch.nn.Module,
    input_tensor: torch.Tensor,
) -> list[dict[str, Any]]:
    """Compute top-3 feature attributions for a maintenance inference.

    Tries shap.DeepExplainer first; falls back to gradient × input if SHAP is
    unavailable or raises any exception during computation.

    Args:
        model: MaintenanceLSTM (or any nn.Module with matching I/O).
        input_tensor: (1, 1800, 8) float32 tensor.

    Returns:
        List of 3 dicts: [{"feature": <IR terminology>, "contribution": <float>}, ...]
        sorted descending by contribution.  Contributions are normalised to sum to 1.0.
    """
    importance: np.ndarray | None = None

    # --- Try DeepExplainer ---
    try:
        import shap as _shap  # noqa: F401 — just test availability
        importance = _shap_deep_attribution(model, input_tensor)
        log.debug("SHAP DeepExplainer attribution computed successfully.")
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "shap.DeepExplainer unavailable or failed (%s); "
            "falling back to gradient attribution.",
            exc,
        )

    # --- Fall back to gradient × input ---
    if importance is None:
        try:
            importance = _gradient_attribution(model, input_tensor)
            log.debug("Gradient attribution computed as fallback.")
        except Exception as exc2:  # noqa: BLE001
            log.error("Gradient attribution also failed: %s. Returning uniform weights.", exc2)
            importance = np.ones(len(FEATURE_NAMES))

    # --- Build top-3 list ---
    total = float(importance.sum()) or 1.0  # avoid division by zero
    normalised = (importance / total).tolist()

    indexed = sorted(enumerate(normalised), key=lambda t: t[1], reverse=True)
    top3 = indexed[:3]

    result = [
        {
            "feature": IR_TERMINOLOGY[FEATURE_NAMES[idx]],
            "contribution": round(float(score), 4),
        }
        for idx, score in top3
    ]
    return result
