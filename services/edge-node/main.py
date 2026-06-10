"""
RailOS Edge Node Main Agent (Task 5.6)
Ties together all 5 edge-node modules into one running process.
Exposes Prometheus metrics on METRICS_PORT (default 8080).
Satisfies: Req 2 (autonomous operation), Req 33 (network partition), Req 44 (hardware telemetry)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import threading
from typing import NoReturn

import httpx
from prometheus_client import Gauge, start_http_server

# ── Module imports ────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from buffer.circular_buffer import CircularBuffer
from heartbeat.heartbeat_fsm import HeartbeatFSM, State
from alerter.storage_alerter import StorageAlerter
from uploader.reconnect_uploader import upload_buffered_events
from model_store.model_store import ModelStore

# ── Environment ───────────────────────────────────────────────────────────────
PIPELINE_URL    = os.environ.get("PIPELINE_URL", "http://data-pipeline.railos.svc.cluster.local:8080")
BUFFER_DB_PATH  = os.environ.get("BUFFER_DB_PATH", "/data/buffer/events.db")
MODEL_STORE_PATH = os.environ.get("MODEL_STORE_PATH", "/data/models")
METRICS_PORT    = int(os.environ.get("METRICS_PORT", "8080"))
HEARTBEAT_INTERVAL_S = float(os.environ.get("HEARTBEAT_INTERVAL_S", "10"))

# ── Structured JSON logging ───────────────────────────────────────────────────
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "ts":       self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f"),
            "level":    record.levelname,
            "logger":   record.name,
            "msg":      record.getMessage(),
        }
        if record.exc_info:
            log_obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]


log = logging.getLogger("edge_node.main")

# ── Prometheus metrics ────────────────────────────────────────────────────────
# 0 = CONNECTED, 1 = AUTONOMOUS, 2 = RECONNECTING
EDGE_NODE_STATE = Gauge(
    "edge_node_state",
    "Current FSM state of the edge node (0=connected, 1=autonomous, 2=reconnecting)",
)

_STATE_GAUGE_MAP: dict[State, int] = {
    State.CONNECTED:    0,
    State.AUTONOMOUS:   1,
    State.RECONNECTING: 2,
}


# ── FSM state-change callback ─────────────────────────────────────────────────
def _on_state_change(old: State, new: State) -> None:
    log.info(
        "FSM_TRANSITION",
        extra={"old_state": old.name, "new_state": new.name},
    )
    log.info(json.dumps({"event": "FSM_TRANSITION", "from": old.name, "to": new.name}))
    EDGE_NODE_STATE.set(_STATE_GAUGE_MAP[new])

    if new == State.AUTONOMOUS:
        log.warning(json.dumps({"event": "AUTONOMOUS_MODE_ACTIVE"}))
        print("AUTONOMOUS_MODE_ACTIVE", flush=True)
        _start_local_inference()

    elif new == State.RECONNECTING:
        log.info(json.dumps({"event": "RECONNECTING_STARTED"}))
        _do_reconnect_upload()


def _start_local_inference() -> None:
    """Stub: edge node continues local ML inference in autonomous mode."""
    log.info(json.dumps({"event": "LOCAL_INFERENCE_STUB", "status": "running"}))
    # Real implementation would invoke model_store.load_model() and run inference
    # on buffered sensor data. Kept as a stub per task specification.


def _do_reconnect_upload() -> None:
    """Upload all buffered events to the pipeline and signal upload complete."""
    log.info(json.dumps({"event": "RECONNECT_UPLOAD_START"}))
    try:
        uploaded = upload_buffered_events(_buffer)
        log.info(json.dumps({"event": "RECONNECT_UPLOAD_DONE", "uploaded": uploaded}))
        _fsm.record_upload_complete()
    except Exception as exc:
        log.error(json.dumps({"event": "RECONNECT_UPLOAD_ERROR", "error": str(exc)}))


# ── Heartbeat loop ────────────────────────────────────────────────────────────
def _heartbeat_loop(fsm: HeartbeatFSM) -> NoReturn:
    health_url = f"{PIPELINE_URL}/health"
    log.info(json.dumps({"event": "HEARTBEAT_LOOP_START", "url": health_url,
                         "interval_s": HEARTBEAT_INTERVAL_S}))
    while True:
        time.sleep(HEARTBEAT_INTERVAL_S)
        try:
            resp = httpx.post(health_url, timeout=5.0)
            if resp.status_code == 200:
                fsm.record_heartbeat_success()
                log.info(json.dumps({"event": "HEARTBEAT_OK", "status": 200}))
            else:
                fsm.record_heartbeat_failure()
                log.warning(json.dumps({"event": "HEARTBEAT_FAIL",
                                        "status": resp.status_code}))
        except Exception as exc:
            fsm.record_heartbeat_failure()
            log.warning(json.dumps({"event": "HEARTBEAT_FAIL", "error": str(exc)}))

        # Reflect current state in gauge after each beat
        EDGE_NODE_STATE.set(_STATE_GAUGE_MAP[fsm.state])


# ── Module-level singletons (used by callbacks) ───────────────────────────────
_buffer: CircularBuffer
_fsm:    HeartbeatFSM


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    global _buffer, _fsm

    _setup_logging()
    log.info(json.dumps({"event": "EDGE_NODE_STARTING",
                         "pipeline_url": PIPELINE_URL,
                         "metrics_port": METRICS_PORT}))

    # 1. Initialise shared modules
    _buffer     = CircularBuffer(db_path=BUFFER_DB_PATH)
    _fsm        = HeartbeatFSM(on_state_change=_on_state_change)
    model_store = ModelStore(store_path=MODEL_STORE_PATH)  # noqa: F841 — available for inference

    # 2. Start Prometheus HTTP server
    start_http_server(METRICS_PORT)
    EDGE_NODE_STATE.set(_STATE_GAUGE_MAP[_fsm.state])
    log.info(json.dumps({"event": "METRICS_SERVER_STARTED", "port": METRICS_PORT}))

    # 3. Start StorageAlerter thread (daemon — won't prevent clean shutdown)
    alerter = StorageAlerter(_buffer)
    alerter.start()
    log.info(json.dumps({"event": "STORAGE_ALERTER_STARTED"}))

    # 4. Start heartbeat loop in a daemon thread
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(_fsm,),
        daemon=True,
        name="HeartbeatLoop",
    )
    hb_thread.start()
    log.info(json.dumps({"event": "HEARTBEAT_THREAD_STARTED"}))

    log.info(json.dumps({"event": "EDGE_NODE_READY"}))

    # 5. Keep the main thread alive (supervisord / containerd will manage lifecycle)
    while True:
        time.sleep(60)
        log.debug(json.dumps({"event": "EDGE_NODE_ALIVE",
                               "fsm_state": _fsm.state.name,
                               "buffer_pct": round(_buffer.capacity_pct(), 2)}))


if __name__ == "__main__":
    main()
