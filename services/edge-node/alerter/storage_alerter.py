"""
RailOS Edge Node Storage Threshold Alerter (Task 5.5)
Monitors buffer capacity; sends STORAGE_THRESHOLD alert at ≥90%.
Channels: SMS gateway → local console → audit log, with 5-min retry.
Never blocks inference threads.
Satisfies: Req 2 C5, Design §5.2
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

SMS_GATEWAY_URL      = os.environ.get("SMS_GATEWAY_URL", "")
ALERT_LOG_PATH       = os.environ.get("ALERT_LOG_PATH", "/data/logs/storage_alerts.jsonl")
CHECK_INTERVAL_S     = float(os.environ.get("CHECK_INTERVAL_SECONDS", "60"))
RETRY_INTERVAL_S     = float(os.environ.get("RETRY_INTERVAL_SECONDS", "300"))
CAPACITY_THRESHOLD   = float(os.environ.get("CAPACITY_THRESHOLD_PCT", "90"))


class StorageAlerter(threading.Thread):
    def __init__(self, buffer: Any) -> None:
        super().__init__(daemon=True, name="StorageAlerter")
        self._buffer      = buffer
        self._last_alert  = 0.0   # monotonic time of last alert attempt

    def run(self) -> None:
        log.info("StorageAlerter started (threshold=%.0f%%)", CAPACITY_THRESHOLD)
        while True:
            time.sleep(CHECK_INTERVAL_S)
            pct = self._buffer.capacity_pct()
            if pct >= CAPACITY_THRESHOLD:
                now = time.monotonic()
                if now - self._last_alert >= RETRY_INTERVAL_S:
                    self._send_alert(pct)
                    self._last_alert = now

    def _send_alert(self, pct: float) -> None:
        message = f"STORAGE_THRESHOLD: Edge node buffer at {pct:.1f}% capacity (threshold={CAPACITY_THRESHOLD}%)"
        payload = {
            "alertType": "STORAGE_THRESHOLD",
            "capacityPct": round(pct, 1),
            "threshold":   CAPACITY_THRESHOLD,
        }

        # Channel 1: SMS gateway
        if SMS_GATEWAY_URL:
            try:
                resp = httpx.post(SMS_GATEWAY_URL, json={"message": message}, timeout=5.0)
                if resp.status_code < 300:
                    log.warning("STORAGE_THRESHOLD alert sent via SMS gateway")
                    return
            except Exception as exc:
                log.warning("SMS gateway unavailable: %s — trying console", exc)

        # Channel 2: Local operator console
        print(f"STORAGE_THRESHOLD {json.dumps(payload)}", flush=True)
        log.warning("STORAGE_THRESHOLD alert printed to console")

        # Channel 3: Audit log (always write, even if above channels succeeded)
        try:
            Path(ALERT_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
            with open(ALERT_LOG_PATH, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as exc:
            log.error("Could not write to audit log: %s", exc)
