"""
RailOS MARL Conflict-Free Constraint Layer (Task 10.3)
Safety-critical invariant: no two trains share a segment at overlapping times.
Satisfies: Req 7 C2, Design §6.5 — Property 1 PBT target
"""
from __future__ import annotations

from typing import Any


class ConflictViolation(RuntimeError):
    """Raised when a rescheduling proposal contains a scheduling conflict."""


def _windows_overlap(enter_a: str, exit_a: str, enter_b: str, exit_b: str) -> bool:
    """Return True if two time windows overlap: max(enter) < min(exit)."""
    return max(enter_a, enter_b) < min(exit_a, exit_b)


class ConflictChecker:
    """Validates rescheduling proposals for segment occupation conflicts."""

    def is_conflict_free(self, proposal: dict[str, Any]) -> bool:
        """Return True if no two trains occupy the same segment at overlapping times."""
        # Build list of (segment_id, enter_at, exit_at, train_id)
        windows: list[tuple[str, str, str, str]] = []
        for assignment in proposal.get("assignments", []):
            train_id = assignment.get("trainId", "unknown")
            for action in assignment.get("actions", []):
                seg  = action.get("segmentId", "")
                entr = action.get("enterAt", "")
                exit_ = action.get("exitAt", "")
                if seg and entr and exit_:
                    windows.append((seg, entr, exit_, train_id))

        # O(n²) conflict check — acceptable for pilot-scale proposals
        for i in range(len(windows)):
            for j in range(i + 1, len(windows)):
                s1, e1, x1, t1 = windows[i]
                s2, e2, x2, t2 = windows[j]
                if s1 == s2 and _windows_overlap(e1, x1, e2, x2):
                    return False
        return True

    def assert_conflict_free(self, proposal: dict[str, Any]) -> None:
        """Raise ConflictViolation if any conflict is detected."""
        if not self.is_conflict_free(proposal):
            raise ConflictViolation(
                f"Conflict detected in rescheduling proposal id={proposal.get('proposalId','?')}"
            )
