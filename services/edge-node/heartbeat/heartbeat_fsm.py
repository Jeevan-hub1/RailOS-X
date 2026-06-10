"""
RailOS Edge Node Heartbeat FSM (Task 5.1)
3-state FSM: Connected → Autonomous → Reconnecting → Connected
Transition rules:
  Connected  → Autonomous:    3 consecutive failures within 30s window
  Autonomous → Reconnecting:  first successful heartbeat
  Reconnecting → Connected:   buffer upload complete + ACK
Satisfies: Req 2 C1, Req 33 C1, Design §5.2
"""
from __future__ import annotations

import threading
import time
from enum import Enum, auto
from typing import Callable


class State(Enum):
    CONNECTED    = auto()
    AUTONOMOUS   = auto()
    RECONNECTING = auto()


class HeartbeatFSM:
    FAILURE_THRESHOLD = 3
    WINDOW_S          = 30.0

    def __init__(self, on_state_change: Callable[[State, State], None] | None = None) -> None:
        self._state       = State.CONNECTED
        self._lock        = threading.Lock()
        self._failures:   list[float] = []   # timestamps of recent failures
        self._on_change   = on_state_change or (lambda old, new: None)

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def record_heartbeat_success(self) -> State:
        """Call when a heartbeat to the central pipeline succeeds."""
        with self._lock:
            self._failures.clear()
            if self._state == State.AUTONOMOUS:
                self._transition(State.RECONNECTING)
        return self._state

    def record_heartbeat_failure(self) -> State:
        """Call when a heartbeat attempt fails. Transitions to AUTONOMOUS after threshold."""
        with self._lock:
            now = time.monotonic()
            # Prune failures outside the 30s window
            self._failures = [t for t in self._failures if now - t <= self.WINDOW_S]
            self._failures.append(now)
            if (
                self._state == State.CONNECTED
                and len(self._failures) >= self.FAILURE_THRESHOLD
            ):
                self._transition(State.AUTONOMOUS)
        return self._state

    def record_upload_complete(self) -> State:
        """Call when buffered event upload is complete and ACK received."""
        with self._lock:
            if self._state == State.RECONNECTING:
                self._transition(State.CONNECTED)
        return self._state

    def failure_count(self) -> int:
        with self._lock:
            now = time.monotonic()
            return len([t for t in self._failures if now - t <= self.WINDOW_S])

    def _transition(self, new_state: State) -> None:
        old = self._state
        self._state = new_state
        self._on_change(old, new_state)
