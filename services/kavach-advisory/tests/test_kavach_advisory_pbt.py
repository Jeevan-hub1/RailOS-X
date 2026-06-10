"""
Kavach++ Advisory PBT (Task 11.8) — Property 2:
Advisory stopping distance ≥ certified Kavach 4.0 distance for all v and conditions.
Satisfies: Req 10 C3, Design §6.7
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from kavach_advisory import (
    advisory_stopping_distance,
    kavach_certified_stopping_distance,
    compute_advisory,
)


@given(
    speed_kmh   = st.floats(min_value=0, max_value=160, allow_nan=False, allow_infinity=False),
    vibration   = st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
)
@settings(max_examples=1000)
def test_advisory_stopping_dist_gte_certified(speed_kmh: float, vibration: float):
    """Property 2: advisory_distance(v) ≥ certified_distance(v) for all speeds."""
    result = compute_advisory(speed_kmh=speed_kmh, lat=17.38, lon=78.49, vibration_rms=vibration)
    if result is not None:
        assert result["advisoryStoppingDist_m"] >= result["certifiedStoppingDist_m"] - 1e-6, (
            f"Safety invariant violated: advisory={result['advisoryStoppingDist_m']:.3f} < "
            f"certified={result['certifiedStoppingDist_m']:.3f} at speed={speed_kmh:.1f}km/h"
        )


def test_unavailable_when_no_vibration_data():
    """KAVACH_ADVISORY_UNAVAILABLE when vibration_rms is None."""
    result = compute_advisory(100.0, 17.38, 78.49, vibration_rms=None)
    assert result is None


def test_label_is_advisory_not_certified():
    """All advisories must carry 'ADVISORY — NOT CERTIFIED' label."""
    result = compute_advisory(80.0, 17.38, 78.49, vibration_rms=1.0)
    assert result is not None
    assert result["label"] == "ADVISORY — NOT CERTIFIED"


def test_zero_speed_zero_stopping_distance():
    result = compute_advisory(0.0, 17.38, 78.49, vibration_rms=0.5)
    assert result is not None
    assert result["advisoryStoppingDist_m"] == pytest.approx(0.0, abs=1e-3)
