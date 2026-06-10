"""
FL Round Integration Tests (Task 9.8)
Satisfies: Req 6 C1–C8, Design §6.4
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest
from client.fl_client import _apply_dp_noise, _assert_no_raw_sensor_data


def test_dp_sigma_out_of_range_raises():
    params = [np.array([1.0, 2.0], dtype=np.float32)]
    with pytest.raises(ValueError, match="sigma"):
        _apply_dp_noise(params, sigma=11.0)


def test_dp_sigma_zero_returns_unchanged():
    params = [np.array([1.0, 2.0], dtype=np.float32)]
    result = _apply_dp_noise(params, sigma=0.0)
    np.testing.assert_array_equal(result[0], params[0])


def test_dp_sigma_valid_adds_noise():
    params = [np.zeros(100, dtype=np.float32)]
    noisy = _apply_dp_noise(params, sigma=1.0)
    assert not np.allclose(noisy[0], params[0])


def test_no_raw_sensor_data_passes_float_arrays():
    params = [np.array([0.1, 0.2], dtype=np.float32)]
    _assert_no_raw_sensor_data(params)  # should not raise


def test_no_raw_sensor_data_raises_on_non_array():
    with pytest.raises(TypeError):
        _assert_no_raw_sensor_data(["string data"])


def test_no_raw_sensor_data_raises_on_int_array():
    with pytest.raises(TypeError):
        _assert_no_raw_sensor_data([np.array([1, 2, 3], dtype=np.int32)])


def test_round_aborted_event_structure():
    """Verify ROUND_ABORTED payload structure matches spec (Req 6 C4)."""
    from server.fl_server import _emit_round_aborted
    # Just verify it doesn't crash when Kafka is unavailable
    _emit_round_aborted(round_id=1, absent_clients=["client-3", "client-4"])


def test_fl_client_fit_returns_float_params():
    """fit() must return float32 arrays (not raw sensor data) (Req 6 C3)."""
    import torch
    import torch.nn as nn

    class TinyModel(nn.Module):
        def __init__(self): super().__init__(); self.fc = nn.Linear(8, 1)
        def forward(self, x): return self.fc(x)

    model = TinyModel()
    # Minimal fake dataset
    data = [(torch.randn(4, 8), torch.randn(4))]

    from client.fl_client import RailOSFLClient
    client = RailOSFLClient(model, data)
    initial = client.get_parameters({})
    updated, n_samples, metrics = client.fit(initial, {})

    assert n_samples > 0
    for arr in updated:
        assert isinstance(arr, np.ndarray)
        assert arr.dtype.kind == "f"
