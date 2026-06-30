"""
RailOS Alert Fatigue Management (Tasks 29.1–29.4)
Geographic deduplication, advisory update-in-place, suppression counter display.
Suppression window configurable via Vault (Task 29.4).
Satisfies: Req 29, Design §14
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

SUPPRESSION_WINDOW_S = float(os.environ.get("DEFECT_SUPPRESSION_WINDOW_SECONDS", "600"))
SUPPRESSION_RADIUS_M = float(os.environ.get("DEFECT_SUPPRESSION_RADIUS_METERS", "50"))


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two GPS coordinates."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class AlertDeduplicator:
    """Deduplicates DEFECT_ALERT and MAINTENANCE_ADVISORY events.

    Tasks 29.1: DEFECT_ALERT dedup within 50m radius + same category + 10min window
    Tasks 29.2: MAINTENANCE_ADVISORY update-in-place for same asset
    Tasks 29.3: suppression counter exposed on each active alert
    Tasks 29.4: suppression window read from Vault config
    """

    def __init__(self) -> None:
        # key: (category, asset_id_or_coord_bucket) → {alert, count, last_ts}
        self._active_defect: dict[str, dict] = {}
        self._active_maintenance: dict[str, dict] = {}

    def process_defect_alert(self, alert: dict[str, Any]) -> tuple[bool, Optional[dict]]:
        """Returns (is_duplicate, original_alert_with_updated_count).

        If duplicate: returns (True, updated original). If new: returns (False, alert).
        """
        cat = alert.get("defectCategory", "unknown")
        gps = alert.get("gps", {})
        lat, lon = float(gps.get("lat", 0)), float(gps.get("lon", 0))
        now = time.monotonic()

        for key, entry in list(self._active_defect.items()):
            orig = entry["alert"]
            orig_gps = orig.get("gps", {})
            dist = _haversine_distance(
                lat, lon,
                float(orig_gps.get("lat", 0)), float(orig_gps.get("lon", 0))
            )
            age = now - entry["first_seen"]
            if (dist <= SUPPRESSION_RADIUS_M
                    and orig.get("defectCategory") == cat
                    and age <= SUPPRESSION_WINDOW_S):
                entry["count"] += 1
                entry["alert"]["suppressedCount"] = entry["count"]
                log.debug("Defect alert suppressed: dist=%.1fm cat=%s count=%d",
                          dist, cat, entry["count"])
                return True, entry["alert"]

        # New alert
        key = f"{cat}:{round(lat,4)}:{round(lon,4)}"
        alert["suppressedCount"] = 0
        self._active_defect[key] = {"alert": alert, "count": 0, "first_seen": now}
        return False, alert

    def process_maintenance_advisory(self, advisory: dict[str, Any]) -> tuple[bool, dict]:
        """Update-in-place for same asset; return (was_updated, advisory)."""
        asset_id = advisory.get("assetId", "unknown")
        if asset_id in self._active_maintenance:
            # Update existing entry (Task 29.2)
            existing = self._active_maintenance[asset_id]["advisory"]
            existing["failureProbability"] = advisory.get("failureProbability",
                                                           existing.get("failureProbability"))
            existing["ciLower"]    = advisory.get("ciLower",    existing.get("ciLower"))
            existing["ciUpper"]    = advisory.get("ciUpper",    existing.get("ciUpper"))
            existing["timestamp_utc"] = advisory.get("timestamp_utc", existing.get("timestamp_utc"))
            log.debug("Maintenance advisory updated in-place: asset=%s", asset_id)
            return True, existing
        # New entry
        self._active_maintenance[asset_id] = {"advisory": advisory}
        return False, advisory

    def get_active_alerts_with_counts(self) -> list[dict]:
        """Return all active alerts with suppression counters (Task 29.3)."""
        result = []
        for entry in self._active_defect.values():
            result.append({**entry["alert"], "suppressedCount": entry["count"]})
        for entry in self._active_maintenance.values():
            result.append(entry["advisory"])
        return result

    def reload_suppression_window(self) -> None:
        """Reload suppression window from Vault (Task 29.4)."""
        global SUPPRESSION_WINDOW_S
        try:
            from services.safety_compliance.vault_config import read_config
            cfg = read_config("suppression")
            SUPPRESSION_WINDOW_S = float(
                cfg.get("defect_alert_suppression_window_seconds", SUPPRESSION_WINDOW_S)
            )
            log.info("Suppression window reloaded from Vault: %.0fs", SUPPRESSION_WINDOW_S)
        except Exception as exc:
            log.warning("Vault suppression window reload failed: %s", exc)
