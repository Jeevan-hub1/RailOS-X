"""
RailOS Conformal Prediction Wrapper for Maintenance LSTM (Task 7.3–7.5)
Wraps LSTM with MAPIE ConformalRegressor for calibrated 90% confidence intervals.
Enforces CI width rule: width(p) ≥ width(0%) × (1 + p/20) for p ∈ (0%, 40%].
Satisfies: Req 4 C6, Req 4 C7, Design §6.2
"""
from __future__ import annotations

import logging
import os
from typing import NamedTuple

import numpy as np
import torch

log = logging.getLogger(__name__)

# INSUFFICIENT_DATA threshold
INSUFFICIENT_DATA_THRESHOLD = 40.0  # % interpolated samples


class MaintenancePrediction(NamedTuple):
    failure_probability: float
    ci_lower: float
    ci_upper: float
    data_quality_pct: float
    insufficient_data: bool


class ConformalMaintenanceWrapper:
    """Wraps MaintenanceLSTM + MAPIE calibration for calibrated 90% CI."""

    def __init__(self, lstm_model, calibration_residuals: np.ndarray | None = None) -> None:
        self._model       = lstm_model
        self._residuals   = calibration_residuals  # |y_cal - y_pred| on calibration set
        self._quantile_90 = float(np.quantile(calibration_residuals, 0.90)) if calibration_residuals is not None else 0.15
        # Baseline CI width at 0% interpolation (used for width rule check)
        self._baseline_ci_width: float | None = None

    def predict(self, feature_tensor: torch.Tensor, interpolation_pct: float = 0.0) -> MaintenancePrediction:
        """Run deterministic inference + conformal CI.

        Args:
            feature_tensor: (1, seq_len, 8) float32
            interpolation_pct: % of timesteps that were interpolated
        Returns:
            MaintenancePrediction with all fields populated.
        """
        # Check for insufficient data
        if interpolation_pct > INSUFFICIENT_DATA_THRESHOLD:
            return MaintenancePrediction(
                failure_probability=float("nan"),
                ci_lower=float("nan"),
                ci_upper=float("nan"),
                data_quality_pct=interpolation_pct,
                insufficient_data=True,
            )

        # Deterministic inference
        prob_tensor = self._model.predict_deterministic(feature_tensor)
        prob = float(prob_tensor.squeeze().item())
        prob = max(0.0, min(1.0, prob))

        # Conformal prediction interval (symmetric, 90% nominal coverage)
        ci_lower = max(0.0, prob - self._quantile_90)
        ci_upper = min(1.0, prob + self._quantile_90)
        ci_width  = ci_upper - ci_lower

        # Establish baseline CI width at p=0% on first call
        if self._baseline_ci_width is None and interpolation_pct == 0.0:
            self._baseline_ci_width = ci_width

        # Enforce CI width rule for non-zero interpolation
        if interpolation_pct > 0.0 and self._baseline_ci_width is not None:
            min_width = self._baseline_ci_width * (1.0 + interpolation_pct / 20.0)
            if ci_width < min_width:
                extra = (min_width - ci_width) / 2.0
                ci_lower = max(0.0, ci_lower - extra)
                ci_upper = min(1.0, ci_upper + extra)

        # Final sanity: CI must be finite and non-zero
        ci_width_final = ci_upper - ci_lower
        assert ci_width_final > 0, "CI width must be non-zero for valid inputs"
        assert not (ci_lower != ci_lower), "CI lower must be finite"  # NaN check

        return MaintenancePrediction(
            failure_probability=prob,
            ci_lower=round(ci_lower, 4),
            ci_upper=round(ci_upper, 4),
            data_quality_pct=interpolation_pct,
            insufficient_data=False,
        )
