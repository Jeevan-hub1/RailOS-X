"""Unit tests for services.model_governance.benchmark_gate."""
from __future__ import annotations

from unittest.mock import patch


from services.model_governance.benchmark_gate import (
    check_regression,
    emit_regression_alert,
    load_deployed_baseline,
    BENCHMARK_REGISTRY,
    REGRESSION_THRESHOLD,
)


class TestCheckRegression:
    def test_no_regression_within_tolerance(self):
        # candidate slightly worse but within 5%
        assert check_regression("m1", "precision", 0.90, 0.87) is True

    def test_regression_detected(self):
        # candidate is much worse (>5% degradation)
        with patch("services.model_governance.benchmark_gate.emit_regression_alert"):
            result = check_regression("m1", "precision", 0.90, 0.50)
        assert result is False

    def test_improvement_passes(self):
        # candidate better than deployed
        assert check_regression("m1", "precision", 0.85, 0.92) is True

    def test_deployed_zero_always_passes(self):
        assert check_regression("m1", "metric", 0.0, 0.5) is True

    def test_just_within_threshold_passes(self):
        deployed = 1.0
        # candidate 4.9% worse — within tolerance
        candidate = deployed * (1 - REGRESSION_THRESHOLD + 0.001)
        assert check_regression("m1", "metric", deployed, candidate) is True

    def test_just_beyond_threshold(self):
        deployed = 1.0
        candidate = deployed * (1 - REGRESSION_THRESHOLD) - 0.001
        with patch("services.model_governance.benchmark_gate.emit_regression_alert"):
            result = check_regression("m1", "metric", deployed, candidate)
        assert result is False


class TestEmitRegressionAlert:
    @patch("services.model_governance.benchmark_gate.KafkaProducer", create=True)
    def test_alert_payload_structure(self, mock_kp_cls):
        # This test just verifies the function doesn't crash without Kafka
        emit_regression_alert("defect_detector", "precision", 0.90, 0.80)

    def test_alert_without_kafka(self):
        # Should log warning but not raise
        emit_regression_alert("model-X", "recall", 0.9, 0.7)


class TestLoadDeployedBaseline:
    def test_fallback_to_registry(self):
        baseline = load_deployed_baseline("defect_detector")
        assert baseline == BENCHMARK_REGISTRY["defect_detector"]

    def test_unknown_model_returns_empty(self):
        baseline = load_deployed_baseline("nonexistent_model_xyz")
        assert baseline == {}

    def test_registry_has_expected_models(self):
        for model_id in ["defect_detector", "maintenance_engine", "delay_predictor", "marl_scheduler"]:
            assert model_id in BENCHMARK_REGISTRY
            assert len(BENCHMARK_REGISTRY[model_id]) > 0
