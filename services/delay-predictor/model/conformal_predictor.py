"""
RailOS Conformal Delay Predictor (Task 8.3)
Wraps HetGNN with MAPIE-style conformal prediction for 90% PI.
Satisfies: Req 5 C1, Design §6.3
"""
from __future__ import annotations
import numpy as np
from typing import Any


class ConformalDelayPredictor:
    """Wraps HetGNN with calibration residuals for 90% conformal PI."""

    def __init__(self, model, calibration_residuals: np.ndarray | None = None) -> None:
        self._model = model
        residuals = calibration_residuals if calibration_residuals is not None else np.array([5.0])
        self._q90 = float(np.quantile(residuals, 0.90))

    def predict(self, hetero_data: Any) -> dict[int, tuple[float, float, float]]:
        """Returns {train_idx: (point_estimate, ci_lower, ci_upper)}."""
        point_preds = self._model.predict(hetero_data)
        result = {}
        for idx, delay in point_preds.items():
            ci_lower = delay - self._q90
            ci_upper = delay + self._q90
            result[idx] = (round(delay, 2), round(ci_lower, 2), round(ci_upper, 2))
        return result
