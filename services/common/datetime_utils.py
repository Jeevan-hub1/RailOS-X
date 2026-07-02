"""
RailOS Shared UTC Timestamp Helper
====================================
Provides a single ``now_iso()`` function used across all services that need
the current UTC timestamp in ISO-8601 format.
"""
from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
