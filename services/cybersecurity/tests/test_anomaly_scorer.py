"""Unit tests for services.cybersecurity.anomaly_scorer."""
from __future__ import annotations

from unittest.mock import patch, MagicMock


from services.cybersecurity.anomaly_scorer import (
    SCADAAnomalyDetector,
    _add_bytes_to_tar,
    WINDOW_SIZE,
    MSE_THRESHOLD,
)
from services.cybersecurity.lstm_autoencoder import LSTMAutoencoder


class TestSCADAAnomalyDetector:
    def _make_detector(self) -> SCADAAnomalyDetector:
        detector = SCADAAnomalyDetector()
        detector._model = LSTMAutoencoder()
        return detector

    def test_window_not_full_returns_none(self):
        detector = self._make_detector()
        result = detector.process_message(b'{"x":1}', [0.0] * 5)
        assert result is None

    def test_window_fills_and_evaluates(self):
        detector = self._make_detector()
        results = []
        for i in range(WINDOW_SIZE):
            r = detector.process_message(b'{"x":1}', [0.1] * 5)
            results.append(r)
        # The first WINDOW_SIZE-1 calls return None; the last may return an alert or None
        assert all(r is None for r in results[:-1])

    def test_sliding_window_maintains_correct_size(self):
        detector = self._make_detector()
        for i in range(WINDOW_SIZE + 5):
            detector.process_message(b'{"x":1}', [0.1] * 5)
        # After sliding, window should be WINDOW_SIZE - STRIDE + extra
        assert len(detector._window) <= WINDOW_SIZE

    def test_evaluate_window_no_model_returns_none(self):
        detector = SCADAAnomalyDetector()
        detector._model = None
        detector._window = [[0.0] * 5] * WINDOW_SIZE
        assert detector._evaluate_window() is None

    def test_evaluate_window_above_threshold_returns_alert(self):
        detector = self._make_detector()
        # Use a model that returns high MSE
        mock_model = MagicMock()
        mock_model.reconstruction_error.return_value = MSE_THRESHOLD + 0.1
        detector._model = mock_model
        detector._window = [[0.1] * 5] * WINDOW_SIZE
        detector._raw_msgs = [b'msg'] * WINDOW_SIZE

        with patch.object(detector, "_capture_forensic_evidence"):
            result = detector._evaluate_window()

        assert result is not None
        assert result["alertType"] == "SECURITY_ANOMALY"
        assert result["acknowledged"] is False
        assert result["reconstructionError"] == round(MSE_THRESHOLD + 0.1, 6)

    def test_evaluate_window_below_threshold_returns_none(self):
        detector = self._make_detector()
        mock_model = MagicMock()
        mock_model.reconstruction_error.return_value = MSE_THRESHOLD - 0.01
        detector._model = mock_model
        detector._window = [[0.1] * 5] * WINDOW_SIZE
        detector._raw_msgs = [b'msg'] * WINDOW_SIZE

        result = detector._evaluate_window()
        assert result is None

    def test_load_model_with_missing_path(self):
        detector = SCADAAnomalyDetector()
        with patch("os.path.exists", return_value=False):
            detector.load_model()
        assert detector._model is not None  # Falls back to untrained model


class TestAddBytesToTar:
    def test_adds_data_to_tar(self):
        import tarfile
        from io import BytesIO

        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            _add_bytes_to_tar(tar, "test.txt", b"hello world")

        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            member = tar.getmembers()[0]
            assert member.name == "test.txt"
            assert member.size == 11
            content = tar.extractfile(member).read()
            assert content == b"hello world"
