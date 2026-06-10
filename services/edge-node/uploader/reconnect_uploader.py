"""
RailOS Reconnect Uploader (Task 5.3)
Uploads buffered events to the Data_Pipeline on reconnection.
Timestamp-ordered, per-record ACK, 3 retries per record, continue-on-failure.
Satisfies: Req 2 C3, Design §5.2
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx
from prometheus_client import Counter

log = logging.getLogger(__name__)

PIPELINE_URL     = os.environ.get("PIPELINE_URL", "http://data-pipeline.railos.svc.cluster.local:8080")
UPLOAD_ENDPOINT  = f"{PIPELINE_URL}/api/v1/events"
MAX_RETRIES      = 3
RETRY_DELAY_S    = 20.0
BATCH_SIZE       = 100

upload_events_total   = Counter("edge_upload_events_total",   "Total events successfully uploaded on reconnect")
upload_failures_total = Counter("edge_upload_failures_total", "Total events that failed all retries on upload")


def upload_buffered_events(buffer: Any) -> int:
    """Upload all buffered events to the Data_Pipeline.

    Returns the number of successfully uploaded events.
    """
    uploaded = 0
    while True:
        batch = buffer.read_oldest(BATCH_SIZE)
        if not batch:
            break  # Buffer drained

        for event in batch:
            buf_id   = event.pop("_buffer_event_id", None)
            event_id = event.get("eventId", "unknown")
            success  = _upload_with_retry(event, event_id)
            if success:
                if buf_id:
                    buffer.ack(buf_id)
                upload_events_total.inc()
                uploaded += 1
            else:
                upload_failures_total.inc()
                log.error(
                    "UPLOAD_FAILED event_id=%s — skipping, event remains in buffer",
                    event_id,
                )
                # Continue to next event rather than halting upload

    log.info("Reconnect upload complete: %d events uploaded", uploaded)
    return uploaded


def _upload_with_retry(event: dict, event_id: str) -> bool:
    """POST event to pipeline. Returns True on success, False after all retries."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                UPLOAD_ENDPOINT,
                json=event,
                timeout=10.0,
            )
            if resp.status_code == 200:
                return True
            log.warning(
                "Upload attempt %d/%d HTTP %d for event_id=%s",
                attempt, MAX_RETRIES, resp.status_code, event_id,
            )
        except Exception as exc:
            log.warning(
                "Upload attempt %d/%d exception for event_id=%s: %s",
                attempt, MAX_RETRIES, event_id, exc,
            )
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_S)

    return False
