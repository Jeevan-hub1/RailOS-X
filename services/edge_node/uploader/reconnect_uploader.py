"""
RailOS Reconnect Uploader (Task 5.3)
Uploads buffered events to the Data_Pipeline on reconnection.
Timestamp-ordered, per-record ACK, 3 retries per record, continue-on-failure.
Satisfies: Req 2 C3, Design §5.2
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable, Optional

import aiohttp
import httpx
from prometheus_client import Counter

log = logging.getLogger(__name__)

PIPELINE_URL     = os.environ.get("PIPELINE_URL", "http://data-pipeline.railos.svc.cluster.local:8080")
UPLOAD_ENDPOINT  = f"{PIPELINE_URL}/api/v1/events"
MAX_RETRIES      = 3
RETRY_DELAY_S    = 20.0
BATCH_SIZE       = 100

edge_upload_events_total   = Counter("edge_upload_events_total",   "Total events successfully uploaded on reconnect")
edge_upload_failures_total = Counter("edge_upload_failures_total", "Total events that failed all retries on upload")


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
                edge_upload_events_total.inc()
                uploaded += 1
            else:
                edge_upload_failures_total.inc()
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



class ReconnectUploader:
    """Asynchronous, timestamp-ordered uploader of buffered events on reconnect.

    Drains the circular buffer oldest-first, POSTing each event to the
    Data_Pipeline with per-record ACK and bounded retries. Events that exhaust
    all retries are left in the buffer (continue-on-failure) so they are not
    lost. When the buffer is drained, a ``reconnect_upload_complete`` event is
    emitted on the optional event bus.

    Satisfies: Req 2 C3, Design 5.2
    """

    def __init__(
        self,
        buffer: Any,
        pipeline_url: str = PIPELINE_URL,
        batch_size: int = BATCH_SIZE,
        retry_count: int = MAX_RETRIES,
        retry_delay: float = RETRY_DELAY_S,
        event_bus: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> None:
        self._buffer = buffer
        self._pipeline_url = pipeline_url.rstrip("/")
        self._upload_endpoint = f"{self._pipeline_url}/api/v1/events"
        self._batch_size = batch_size
        self._retry_count = retry_count
        self._retry_delay = retry_delay
        self._event_bus = event_bus

    async def start(self) -> int:
        """Drain the buffer once. Returns the number of events uploaded.

        Events that fail all retries remain in the buffer and are not retried
        again within this drain pass (preventing an infinite loop on a record
        the pipeline keeps rejecting).
        """
        uploaded = 0
        failed_ids: set[str] = set()

        async with aiohttp.ClientSession() as session:
            while True:
                batch = self._buffer.read_oldest(self._batch_size)
                pending = [e for e in batch if e.get("_buffer_event_id") not in failed_ids]
                if not pending:
                    break

                for event in pending:
                    buf_id = event.pop("_buffer_event_id", None)
                    event_id = event.get("event_id") or event.get("eventId", "unknown")
                    success = await self._upload_with_retry(session, event, event_id)
                    if success:
                        if buf_id is not None:
                            self._buffer.ack(buf_id)
                        edge_upload_events_total.inc()
                        uploaded += 1
                    else:
                        edge_upload_failures_total.inc()
                        if buf_id is not None:
                            failed_ids.add(buf_id)
                        log.error(
                            "UPLOAD_FAILED event_id=%s -- skipping, event remains in buffer",
                            event_id,
                        )

        await self._emit_complete(uploaded)
        log.info("Reconnect upload complete: %d events uploaded", uploaded)
        return uploaded

    async def _upload_with_retry(self, session: Any, event: dict, event_id: str) -> bool:
        """POST a single event, retrying up to ``retry_count`` times."""
        for attempt in range(1, self._retry_count + 1):
            try:
                resp = await session.post(self._upload_endpoint, json=event, timeout=10.0)
                if getattr(resp, "status", None) == 200:
                    return True
                log.warning(
                    "Upload attempt %d/%d HTTP %s for event_id=%s",
                    attempt, self._retry_count, getattr(resp, "status", "?"), event_id,
                )
            except Exception as exc:  # noqa: BLE001 - continue-on-failure semantics
                log.warning(
                    "Upload attempt %d/%d exception for event_id=%s: %s",
                    attempt, self._retry_count, event_id, exc,
                )
            if attempt < self._retry_count:
                await asyncio.sleep(self._retry_delay)
        return False

    async def _emit_complete(self, uploaded: int) -> None:
        if self._event_bus is not None:
            await self._event_bus("reconnect_upload_complete", {"uploaded": uploaded})
