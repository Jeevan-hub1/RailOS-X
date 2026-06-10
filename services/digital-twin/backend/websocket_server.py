"""
RailOS Digital Twin WebSocket Server (Task 13.5)
Pushes state updates to connected frontend clients every 5 seconds.
Satisfies: Req 8 C1, Design §7.1 Layer E
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from prometheus_client import Gauge, start_http_server

from .state_store import DigitalTwinStateStore, ConflictDetector

log = logging.getLogger(__name__)

PUSH_INTERVAL_S = float(os.environ.get("PUSH_INTERVAL_SECONDS", "5"))
METRICS_PORT    = int(os.environ.get("METRICS_PORT", "8085"))
APP_PORT        = int(os.environ.get("APP_PORT", "3000"))

connected_clients = Gauge("digital_twin_connected_clients", "WebSocket clients connected")

app = FastAPI(title="RailOS Digital Twin", docs_url=None)
state_store = DigitalTwinStateStore()
_clients: list[WebSocket] = []


@app.on_event("startup")
def _startup() -> None:
    start_http_server(METRICS_PORT)
    # Start Kafka consumer in background thread
    import threading
    t = threading.Thread(target=state_store.run_consumer_loop, daemon=True)
    t.start()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/state")
def get_state() -> dict:
    """REST endpoint returning current Digital Twin state snapshot."""
    return state_store.get_state()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _clients.append(ws)
    connected_clients.inc()
    log.info("WebSocket client connected (total=%d)", len(_clients))
    try:
        while True:
            state = state_store.get_state()
            await ws.send_text(json.dumps({
                "type":      "state_update",
                "timestamp": _now_iso(),
                "data":      state,
            }))
            await asyncio.sleep(PUSH_INTERVAL_S)
    except WebSocketDisconnect:
        pass
    finally:
        _clients.remove(ws)
        connected_clients.dec()
        log.info("WebSocket client disconnected (total=%d)", len(_clients))


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
