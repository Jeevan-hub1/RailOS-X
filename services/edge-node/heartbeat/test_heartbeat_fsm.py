    """Unit tests for HeartbeatFSM (Task 5.1)"""
import time
import pytest
from heartbeat_fsm import HeartbeatFSM, State


def test_initial_state_is_connected():
    fsm = HeartbeatFSM()
    assert fsm.state == State.CONNECTED


def test_transitions_to_autonomous_after_3_failures():
    fsm = HeartbeatFSM()
    fsm.record_heartbeat_failure()
    fsm.record_heartbeat_failure()
    assert fsm.state == State.CONNECTED  # not yet
    fsm.record_heartbeat_failure()
    assert fsm.state == State.AUTONOMOUS


def test_resets_counter_on_success():
    fsm = HeartbeatFSM()
    fsm.record_heartbeat_failure()
    fsm.record_heartbeat_failure()
    fsm.record_heartbeat_success()
    assert fsm.failure_count() == 0
    assert fsm.state == State.CONNECTED


def test_success_from_autonomous_enters_reconnecting():
    fsm = HeartbeatFSM()
    for _ in range(3):
        fsm.record_heartbeat_failure()
    assert fsm.state == State.AUTONOMOUS
    fsm.record_heartbeat_success()
    assert fsm.state == State.RECONNECTING


def test_reconnecting_to_connected_after_upload():
    fsm = HeartbeatFSM()
    for _ in range(3):
        fsm.record_heartbeat_failure()
    fsm.record_heartbeat_success()
    fsm.record_upload_complete()
    assert fsm.state == State.CONNECTED


def test_consecutive_failures_must_be_within_30s_window(monkeypatch):
    """Failures older than 30s are pruned and don't count toward threshold."""
    fsm = HeartbeatFSM()
    times = [0.0, 1.0, 35.0]  # last failure is >30s after first
    call_count = [0]

    original_monotonic = time.monotonic

    def fake_monotonic():
        idx = min(call_count[0], len(times) - 1)
        call_count[0] += 1
        return times[idx]

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    fsm.record_heartbeat_failure()  # t=0
    fsm.record_heartbeat_failure()  # t=1
    fsm.record_heartbeat_failure()  # t=35 — first two are outside window
    # Only 1 failure within the last 30s, so should not be AUTONOMOUS
    assert fsm.state == State.CONNECTED


def test_on_state_change_callback_called():
    transitions = []
    fsm = HeartbeatFSM(on_state_change=lambda old, new: transitions.append((old, new)))
    for _ in range(3):
        fsm.record_heartbeat_failure()
    assert (State.CONNECTED, State.AUTONOMOUS) in transitions
