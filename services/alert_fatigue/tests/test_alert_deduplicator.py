"""Unit tests for services.alert_fatigue.alert_deduplicator."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from services.alert_fatigue.alert_deduplicator import (
    AlertDeduplicator,
    _haversine_distance,
)


# ── _haversine_distance ─────────────────────────────────────────────────────

class TestHaversineDistance:
    def test_same_point_returns_zero(self):
        assert _haversine_distance(28.6139, 77.2090, 28.6139, 77.2090) == pytest.approx(0.0, abs=0.01)

    def test_known_distance(self):
        # Delhi (28.6139, 77.2090) to Agra (27.1767, 78.0081) ≈ 178 km
        dist = _haversine_distance(28.6139, 77.2090, 27.1767, 78.0081)
        assert 170_000 < dist < 190_000

    def test_short_distance(self):
        # Two points ~10m apart (small lat offset)
        lat1, lon1 = 28.6139, 77.2090
        lat2 = lat1 + 0.0001  # ~11m
        dist = _haversine_distance(lat1, lon1, lat2, lon1)
        assert 5 < dist < 20

    def test_symmetric(self):
        d1 = _haversine_distance(10.0, 20.0, 30.0, 40.0)
        d2 = _haversine_distance(30.0, 40.0, 10.0, 20.0)
        assert d1 == pytest.approx(d2, rel=1e-9)


# ── AlertDeduplicator.process_defect_alert ───────────────────────────────────

class TestProcessDefectAlert:
    def test_first_alert_is_not_duplicate(self):
        dedup = AlertDeduplicator()
        alert = {"defectCategory": "crack", "gps": {"lat": 28.6, "lon": 77.2}}
        is_dup, result = dedup.process_defect_alert(alert)
        assert is_dup is False
        assert result["suppressedCount"] == 0

    def test_duplicate_within_radius_and_window(self):
        dedup = AlertDeduplicator()
        base = {"defectCategory": "crack", "gps": {"lat": 28.600000, "lon": 77.200000}}
        dedup.process_defect_alert(base)

        # Nearby alert (within 50m), same category
        nearby = {"defectCategory": "crack", "gps": {"lat": 28.600001, "lon": 77.200001}}
        is_dup, result = dedup.process_defect_alert(nearby)
        assert is_dup is True
        assert result["suppressedCount"] == 1

    def test_different_category_not_duplicate(self):
        dedup = AlertDeduplicator()
        a1 = {"defectCategory": "crack", "gps": {"lat": 28.6, "lon": 77.2}}
        a2 = {"defectCategory": "flaking", "gps": {"lat": 28.6, "lon": 77.2}}
        dedup.process_defect_alert(a1)
        is_dup, _ = dedup.process_defect_alert(a2)
        assert is_dup is False

    def test_far_apart_not_duplicate(self):
        dedup = AlertDeduplicator()
        a1 = {"defectCategory": "crack", "gps": {"lat": 28.6, "lon": 77.2}}
        a2 = {"defectCategory": "crack", "gps": {"lat": 29.0, "lon": 78.0}}
        dedup.process_defect_alert(a1)
        is_dup, _ = dedup.process_defect_alert(a2)
        assert is_dup is False

    def test_suppression_count_increments(self):
        dedup = AlertDeduplicator()
        base = {"defectCategory": "crack", "gps": {"lat": 28.6, "lon": 77.2}}
        dedup.process_defect_alert(base)

        for i in range(1, 4):
            dup = {"defectCategory": "crack", "gps": {"lat": 28.6, "lon": 77.2}}
            is_dup, result = dedup.process_defect_alert(dup)
            assert is_dup is True
            assert result["suppressedCount"] == i

    def test_missing_gps_defaults_to_zero(self):
        dedup = AlertDeduplicator()
        a = {"defectCategory": "crack"}  # no gps key
        is_dup, result = dedup.process_defect_alert(a)
        assert is_dup is False
        assert result["suppressedCount"] == 0


# ── AlertDeduplicator.process_maintenance_advisory ───────────────────────────

class TestProcessMaintenanceAdvisory:
    def test_first_advisory_not_updated(self):
        dedup = AlertDeduplicator()
        adv = {"assetId": "BRG-001", "failureProbability": 0.3}
        was_updated, result = dedup.process_maintenance_advisory(adv)
        assert was_updated is False
        assert result["failureProbability"] == 0.3

    def test_same_asset_updates_in_place(self):
        dedup = AlertDeduplicator()
        adv1 = {"assetId": "BRG-001", "failureProbability": 0.3, "ciLower": 0.1, "ciUpper": 0.5}
        dedup.process_maintenance_advisory(adv1)

        adv2 = {"assetId": "BRG-001", "failureProbability": 0.7, "ciLower": 0.5, "ciUpper": 0.9}
        was_updated, result = dedup.process_maintenance_advisory(adv2)
        assert was_updated is True
        assert result["failureProbability"] == 0.7
        assert result["ciLower"] == 0.5
        assert result["ciUpper"] == 0.9

    def test_different_asset_not_updated(self):
        dedup = AlertDeduplicator()
        dedup.process_maintenance_advisory({"assetId": "BRG-001", "failureProbability": 0.3})
        was_updated, _ = dedup.process_maintenance_advisory({"assetId": "BRG-002", "failureProbability": 0.5})
        assert was_updated is False


# ── AlertDeduplicator.get_active_alerts_with_counts ──────────────────────────

class TestGetActiveAlertsWithCounts:
    def test_empty(self):
        dedup = AlertDeduplicator()
        assert dedup.get_active_alerts_with_counts() == []

    def test_includes_defect_and_maintenance(self):
        dedup = AlertDeduplicator()
        dedup.process_defect_alert({"defectCategory": "crack", "gps": {"lat": 28.6, "lon": 77.2}})
        dedup.process_maintenance_advisory({"assetId": "BRG-001", "failureProbability": 0.3})
        active = dedup.get_active_alerts_with_counts()
        assert len(active) == 2


# ── AlertDeduplicator.reload_suppression_window ──────────────────────────────

class TestReloadSuppressionWindow:
    def test_reload_from_vault_success(self):
        dedup = AlertDeduplicator()
        mock_read = MagicMock(return_value={"defect_alert_suppression_window_seconds": "300"})
        with patch("services.alert_fatigue.alert_deduplicator.read_config", mock_read, create=True):
            with patch.dict("sys.modules", {"services.safety_compliance.vault_config": MagicMock(read_config=mock_read)}):
                dedup.reload_suppression_window()

    def test_reload_vault_failure_does_not_raise(self):
        dedup = AlertDeduplicator()
        with patch.dict("sys.modules", {"services.safety_compliance.vault_config": None}):
            dedup.reload_suppression_window()  # should not raise
