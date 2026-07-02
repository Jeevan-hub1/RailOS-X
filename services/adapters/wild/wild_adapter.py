"""
RailOS WILD Stream Adapter (Task 3.3)
=======================================
Connects to the Wheel Impact Load Detector (WILD) sensor system over TCP,
reads fixed-width 64-byte binary records, normalises each record to a
canonical ``train.telemetry.wild`` event, and publishes it to Kafka.

WILD binary record format (64 bytes total, all big-endian):
  train_id         : 8s   (8-byte UTF-8 string, null-padded)
  timestamp_ms     : Q    (uint64, epoch milliseconds)
  axle_count       : B    (uint8, number of axles: 1–8)
  _padding         : 3x   (3 padding bytes for alignment)
  load_per_axle    : 8f   (8 × float32, kN — unused slots are 0.0)

Total: 8 + 8 + 1 + 3 + 32 = 52 bytes packed, padded to 64 bytes.

Wait — actual struct layout:
  train_id[8] + timestamp_ms[8] + axle_count[1] + pad[3] + load_per_axle[8*4=32] = 52
  12 trailing bytes padding to reach 64.

Dead-letter pattern (Task 3.4):
  - On 3 consecutive parse failures for the same source, emit
    ``LEGACY_ADAPTER_FAILURE`` to ``monitoring.alerts`` and route the raw
    record to ``dead-letter.adapter-failures``.

Prometheus metrics (Task 3.5):
  - adapter_events_total{adapter_name="wild", adapter_version=<VERSION>}
  - adapter_parse_failures_total{adapter_name="wild"}
  - adapter_kafka_publish_errors_total{adapter_name="wild"}
  Served on :8080/metrics.

Design §4.4 / Req 1 / Req 31 / Tasks 3.3, 3.4, 3.5
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

# Add shared library to path when running as a standalone container
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

from shared.canonical_event import CanonicalEvent, QualityFlags
from shared.dead_letter import DeadLetterRouter
from shared.prometheus_metrics import make_metrics, start_metrics_server
from shared.socket_helpers import recv_exactly
from common.kafka_utils import make_kafka_producer, KafkaError
from common.logging_config import configure_logging

# ── Configuration ─────────────────────────────────────────────────────────────
WILD_HOST            = os.environ.get("WILD_HOST", "wild-stream.railos.svc.cluster.local")
WILD_PORT            = int(os.environ.get("WILD_PORT", "9002"))
KAFKA_BOOTSTRAP      = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
TELEMETRY_TOPIC      = "train.telemetry.wild"
ADAPTER_NAME         = "wild"
ADAPTER_VERSION      = os.environ.get("ADAPTER_VERSION", "1.0.0")
METRICS_PORT         = int(os.environ.get("METRICS_PORT", "8080"))
RECONNECT_DELAY_S    = float(os.environ.get("RECONNECT_DELAY_SECONDS", "5"))

# WILD binary record: 64 bytes fixed
# train_id[8s] + timestamp_ms[Q] + axle_count[B] + pad[3x] + load_per_axle[8f] + trailing_pad[12x]
WILD_RECORD_FORMAT   = ">8sQB3x8f12x"
WILD_RECORD_SIZE     = struct.calcsize(WILD_RECORD_FORMAT)  # must be 64
assert WILD_RECORD_SIZE == 64, f"WILD record size mismatch: {WILD_RECORD_SIZE} != 64"

configure_logging()
log = logging.getLogger("wild-adapter")


# ── Kafka producer factory ─────────────────────────────────────────────────────

def make_producer() -> Any:
    return make_kafka_producer(bootstrap_servers=KAFKA_BOOTSTRAP)


# ── Socket I/O helpers ─────────────────────────────────────────────────────────

def read_wild_record(sock: socket.socket) -> bytes:
    """
    Read one 64-byte WILD record from the TCP stream.

    Returns the raw record bytes.
    Raises EOFError if the connection is closed, socket.error on I/O error.
    """
    return recv_exactly(sock, WILD_RECORD_SIZE)


# ── WILD normalisation ─────────────────────────────────────────────────────────

def parse_wild_record(raw_record: bytes) -> CanonicalEvent:
    """
    Decode a 64-byte WILD binary record and return a CanonicalEvent.

    Canonical payload fields:
      train_id (str), axle_loads (list[float]), max_load (float),
      timestamp_utc (str ISO-8601)

    Raises struct.error or ValueError on malformed input.
    """
    if len(raw_record) != WILD_RECORD_SIZE:
        raise ValueError(
            f"WILD record must be exactly {WILD_RECORD_SIZE} bytes, got {len(raw_record)}"
        )

    fields = struct.unpack(WILD_RECORD_FORMAT, raw_record)
    train_id_bytes: bytes = fields[0]
    timestamp_ms: int     = fields[1]
    axle_count: int       = fields[2]
    load_per_axle: tuple  = fields[3:]  # 8 float32 values

    # Decode train_id: strip null padding
    train_id: str = train_id_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")

    # Validate axle_count is within range
    if not (0 < axle_count <= 8):
        raise ValueError(f"axle_count must be 1–8, got {axle_count}")

    # Take only axle_count loads; ignore unused slots
    axle_loads: list[float] = [float(load_per_axle[i]) for i in range(axle_count)]
    max_load: float = max(axle_loads)

    # Convert epoch milliseconds → ISO-8601 UTC string
    timestamp_utc: str = datetime.fromtimestamp(
        timestamp_ms / 1000.0, tz=timezone.utc
    ).isoformat()

    return CanonicalEvent(
        eventId=str(uuid.uuid4()),
        sourceId=f"wild-{train_id}",
        sensorType="wheel_load",
        assetId=f"loco-{train_id}",
        timestamp_utc=timestamp_utc,
        sequence=0,  # WILD records do not carry a sequence number
        payload={
            "train_id": train_id,
            "axle_loads": axle_loads,
            "max_load": max_load,
            "timestamp_utc": timestamp_utc,
        },
        quality_flags=QualityFlags(
            interpolated=False,
            interpolation_pct=0.0,
            clock_reliable=True,
            drift_ms=0.0,
        ),
        schema_version="1.0.0",
    )


# ── Streaming loop ─────────────────────────────────────────────────────────────

def run_stream_loop(producer: Any, metrics: Any, router: DeadLetterRouter) -> None:
    """
    Main loop: connect to WILD TCP server, read 64-byte records continuously.
    Reconnects automatically after any connection error.
    """
    log.info(
        "WILD adapter started: host=%s port=%d topic=%s",
        WILD_HOST,
        WILD_PORT,
        TELEMETRY_TOPIC,
    )
    while True:
        try:
            _stream_until_disconnect(producer, metrics, router)
        except Exception as exc:
            log.error("WILD stream error, reconnecting in %ss: %s", RECONNECT_DELAY_S, exc)
        time.sleep(RECONNECT_DELAY_S)


def _stream_until_disconnect(
    producer: Any,
    metrics: Any,
    router: DeadLetterRouter,
) -> None:
    """Open a single TCP connection and process WILD records until disconnect."""
    with socket.create_connection((WILD_HOST, WILD_PORT), timeout=30) as sock:
        log.info("Connected to WILD at %s:%d", WILD_HOST, WILD_PORT)
        while True:
            try:
                raw_record = read_wild_record(sock)
            except EOFError:
                log.warning("WILD server closed connection")
                return
            except socket.error as exc:
                log.error("WILD socket error: %s", exc)
                return

            source_id = "wild-stream"
            try:
                event = parse_wild_record(raw_record)
                source_id = event.sourceId
            except Exception as exc:
                log.warning("Failed to parse WILD record len=%d: %s", len(raw_record), exc)
                metrics.parse_failures_total.inc()
                router.record_failure(source_id, raw_record)
                continue

            router.reset(source_id)

            try:
                producer.send(TELEMETRY_TOPIC, value=event.to_kafka_message())
                producer.flush(timeout=5)
                metrics.events_total.inc()
                log.debug("Published WILD event: source=%s", event.sourceId)
            except KafkaError as exc:  # type: ignore[misc]
                log.error("Kafka publish error for source=%s: %s", source_id, exc)
                metrics.kafka_publish_errors_total.inc()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    start_metrics_server(METRICS_PORT)
    producer = make_producer()
    metrics = make_metrics(adapter_name=ADAPTER_NAME, adapter_version=ADAPTER_VERSION)
    router = DeadLetterRouter(
        producer=producer,
        adapter_name=ADAPTER_NAME,
        adapter_version=ADAPTER_VERSION,
    )
    run_stream_loop(producer, metrics, router)


if __name__ == "__main__":
    main()
