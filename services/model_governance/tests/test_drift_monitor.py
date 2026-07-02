"""Unit tests for services.model_governance.drift_monitor."""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from services.model_governance import drift_monitor
from services.model_governance.drift_monitor import (
    compute_psi,
    check_drift,
    is_drift_active,
    PSI_THRESHOLD,
    CONSECUTIVE_DAYS,
)


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Reset module-level drift state between tests."""
    drift_monitor._violation_counts.clear()
    drift_monitor._drift_active.clear()
    yield


class TestComputePSI:
    def test_identical_distributions_psi_near_zero(self):
        data = np.random.RandomState(42).normal(0, 1, 1000)
        psi = compute_psi(data, data)
        assert psi == pytest.approx(0.0, abs=0.01)

    def test_shifted_distribution_higher_psi(self):
        rng = np.random.RandomState(42)
        baseline = rng.normal(0, 1, 1000)
        current = rng.normal(3, 1, 1000)  # shifted mean
        psi = compute_psi(baseline, current)
        assert psi > PSI_THRESHOLD

    def test_psi_always_non_negative(self):
        rng = np.random.RandomState(0)
        for _ in range(10):
            b = rng.uniform(0, 10, 500)
            c = rng.uniform(0, 10, 500)
            assert compute_psi(b, c) >= 0.0

    def test_custom_bins(self):
        rng = np.random.RandomState(42)
        b = rng.normal(0, 1, 500)
        c = rng.normal(0, 1, 500)
        psi5 = compute_psi(b, c, bins=5)
        psi20 = compute_psi(b, c, bins=20)
        # Both should be small for similar distributions
        assert psi5 < 0.1
        assert psi20 < 0.1


class TestCheckDrift:
    def test_below_threshold_no_violation(self):
        result = check_drift("model-A", PSI_THRESHOLD - 0.01)
        assert result["drift_warning"] is False
        assert result["consecutive_violations"] == 0
        assert result["alert_emitted"] is False

    def test_single_violation_no_alert(self):
        result = check_drift("model-B", PSI_THRESHOLD + 0.01)
        assert result["consecutive_violations"] == 1
        assert result["alert_emitted"] is False
        assert result["drift_warning"] is False

    @patch("services.model_governance.drift_monitor._emit_drift_alert")
    def test_three_consecutive_violations_emit_alert(self, mock_emit):
        for i in range(CONSECUTIVE_DAYS - 1):
            result = check_drift("model-C", PSI_THRESHOLD + 0.05)
            assert result["alert_emitted"] is False

        result = check_drift("model-C", PSI_THRESHOLD + 0.05)
        assert result["alert_emitted"] is True
        assert result["drift_warning"] is True
        assert result["consecutive_violations"] == CONSECUTIVE_DAYS
        mock_emit.assert_called_once()

    @patch("services.model_governance.drift_monitor._emit_drift_alert")
    def test_violation_counter_resets_on_good_score(self, mock_emit):
        check_drift("model-D", PSI_THRESHOLD + 0.1)
        check_drift("model-D", PSI_THRESHOLD + 0.1)
        # Reset with a good score
        result = check_drift("model-D", PSI_THRESHOLD - 0.1)
        assert result["consecutive_violations"] == 0
        assert result["drift_warning"] is False

    @patch("services.model_governance.drift_monitor._emit_drift_alert")
    def test_alert_not_re_emitted_while_drift_active(self, mock_emit):
        for _ in range(CONSECUTIVE_DAYS):
            check_drift("model-E", PSI_THRESHOLD + 0.1)
        # Alert already emitted once
        mock_emit.assert_called_once()

        # Additional violations should not re-emit
        result = check_drift("model-E", PSI_THRESHOLD + 0.1)
        assert result["drift_warning"] is True
        assert result["alert_emitted"] is False
        assert mock_emit.call_count == 1


class TestIsDriftActive:
    def test_no_drift_by_default(self):
        assert is_drift_active("nonexistent-model") is False

    @patch("services.model_governance.drift_monitor._emit_drift_alert")
    def test_drift_active_after_violations(self, mock_emit):
        for _ in range(CONSECUTIVE_DAYS):
            check_drift("model-F", PSI_THRESHOLD + 0.1)
        assert is_drift_active("model-F") is True
