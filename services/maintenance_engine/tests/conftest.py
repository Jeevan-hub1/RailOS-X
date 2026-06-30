"""
Pytest configuration and shared fixtures for the maintenance-engine test suite.

Fixtures
--------
synthetic_feature_window : (torch.Tensor, float)
    Returns a tuple of:
      - tensor: shape (1, 1800, 8), dtype float32 — deterministic synthetic window
      - interpolation_pct: 0.0 (no data gaps)

wrapped_model : ConformalMaintenanceWrapper
    A freshly instantiated wrapper around an untrained MaintenanceLSTM with
    reproducible calibration residuals.  Suitable for determinism and CI tests.
"""
from __future__ import annotations

import numpy as np
import pytest
import torch

from services.maintenance_engine.model.lstm_model import MaintenanceLSTM
from services.maintenance_engine.model.conformal_wrapper import ConformalMaintenanceWrapper


# ---------------------------------------------------------------------------
# Reproducibility seed (all fixtures use this seed so results are stable)
# ---------------------------------------------------------------------------
_SEED = 42


@pytest.fixture(scope="session")
def synthetic_feature_window() -> tuple[torch.Tensor, float]:
    """Return a (tensor, interpolation_pct) pair for deterministic tests.

    tensor shape : (1, 1800, 8) — one batch, 1800 timesteps, 8 features
    interpolation_pct : 0.0

    The data is generated with a fixed seed so every test run gets the same
    values.  Feature magnitudes are loosely plausible for bogie telemetry:
      vibration_rms ∈ [0, 2],  temperature_bogie ∈ [20, 80],  speed_kmh ∈ [0, 160].
    """
    rng = np.random.default_rng(_SEED)

    seq_len: int = 1800
    n_features: int = 8

    # Feature-specific scales (matches FEATURE_NAMES order in shap_attribution.py)
    scales = np.array([
        2.0,    # vibration_rms     (g)
        5.0,    # vibration_kurtosis
        4.0,    # vibration_peak    (g)
        60.0,   # temperature_bogie (°C) — offset below
        50.0,   # wheel_load_left   (kN)
        50.0,   # wheel_load_right  (kN)
        1.0,    # acoustic_emission_rms
        160.0,  # speed_kmh
    ], dtype=np.float32)

    offsets = np.array([0, 0, 0, 20, 0, 0, 0, 0], dtype=np.float32)

    data = rng.random((seq_len, n_features)).astype(np.float32) * scales + offsets
    tensor = torch.tensor(data, dtype=torch.float32).unsqueeze(0)  # (1, 1800, 8)

    return tensor, 0.0


@pytest.fixture(scope="session")
def wrapped_model() -> ConformalMaintenanceWrapper:
    """Return a ConformalMaintenanceWrapper with fixed calibration residuals.

    Uses a deterministic MaintenanceLSTM in eval mode.  The calibration
    residuals are constant 0.15 so the baseline CI width is fully predictable.
    """
    torch.manual_seed(_SEED)
    model = MaintenanceLSTM()
    model.eval()

    calibration_residuals = np.full(200, 0.15, dtype=np.float32)
    wrapper = ConformalMaintenanceWrapper(
        lstm_model=model,
        calibration_residuals=calibration_residuals,
    )
    return wrapper
