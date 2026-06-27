"""
RailOS MARL Conflict-Free Property-Based Test (Task 10.7)
Property 1: Every MARL proposal must be free of segment occupation conflicts.
Satisfies: Req 7 C2, Design §6.5
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from constraints.conflict_checker import ConflictChecker

checker = ConflictChecker()

# ── Hypothesis strategies ──────────────────────────────────────────────────────

def _time_str(h: int, m: int) -> str:
    return f"{h:02d}:{m:02d}:00"


@st.composite
def disruption_strategy(draw):
    n_trains = draw(st.integers(min_value=1, max_value=10))
    return {
        "disruptionEventId": draw(st.uuids()).hex,
        "type": draw(st.sampled_from(["cancelled_service", "delayed_service", "blocked_segment"])),
        "affectedTrains": [f"TRAIN-{i}" for i in range(n_trains)],
    }


@st.composite
def proposal_strategy(draw):
    """Generate a well-formed rescheduling proposal."""
    n_trains = draw(st.integers(min_value=1, max_value=8))
    assignments = []
    base_min = draw(st.integers(min_value=0, max_value=30))
    for i in range(n_trains):
        enter_min = base_min + i * 12  # sequential, non-overlapping by design
        exit_min  = enter_min + 10
        assignments.append({
            "trainId": f"T{i}",
            "actions": [{
                "segmentId": f"SEG-{draw(st.integers(0, 20))}",
                "enterAt": _time_str(14, enter_min % 60),
                "exitAt":  _time_str(14, exit_min  % 60),
            }],
            "delayDeltaMin": draw(st.integers(-10, 30)),
        })
    return {
        "proposalId": draw(st.uuids()).hex,
        "disruptionEventId": "test",
        "conflictFree": True,
        "assignments": assignments,
    }


@given(disruptions=st.lists(disruption_strategy(), min_size=10, max_size=50))
@settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
def test_marl_scheduler_produces_conflict_free_proposals(disruptions):
    """Property 1: For all disruption inputs, generated proposals must be conflict-free."""
    from service.scheduler_service import _generate_proposal
    for d in disruptions:
        proposal = _generate_proposal(d)
        if proposal is not None:
            assert checker.is_conflict_free(proposal), \
                f"Conflict detected in proposal: proposalId={proposal.get('proposalId')}"


@given(proposal=proposal_strategy())
@settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
def test_conflict_checker_correctly_identifies_conflict_free_proposals(proposal):
    """Conflict checker must accept all sequentially-scheduled (non-overlapping) proposals."""
    assert checker.is_conflict_free(proposal), \
        f"False positive conflict detected in proposal: {proposal}"


def test_conflict_checker_detects_overlapping_segments():
    """Conflict checker must reject proposals where two trains share a segment at the same time."""
    conflicting = {
        "proposalId": "test-conflict",
        "assignments": [
            {"trainId": "T1", "actions": [{"segmentId": "SEG-A", "enterAt": "14:00:00", "exitAt": "14:10:00"}]},
            {"trainId": "T2", "actions": [{"segmentId": "SEG-A", "enterAt": "14:05:00", "exitAt": "14:15:00"}]},
        ],
    }
    assert not checker.is_conflict_free(conflicting)


def test_conflict_checker_accepts_non_overlapping_same_segment():
    """Trains on the same segment but at different times must not be flagged."""
    non_conflicting = {
        "proposalId": "test-ok",
        "assignments": [
            {"trainId": "T1", "actions": [{"segmentId": "SEG-A", "enterAt": "14:00:00", "exitAt": "14:08:00"}]},
            {"trainId": "T2", "actions": [{"segmentId": "SEG-A", "enterAt": "14:10:00", "exitAt": "14:18:00"}]},
        ],
    }
    assert checker.is_conflict_free(non_conflicting)
