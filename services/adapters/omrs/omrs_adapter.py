"""
RailOS OMRS Stream Adapter (Task 3.2)
=======================================
Connects to the On-board Monitoring and Recording System (OMRS) over TCP,
reads length-prefixed binary frames (4-byte big-endian length header +
payload), decodes each frame to a canonical ``train.telemetry.omrs`` event,
and publishes it to Kafka.

Frame format:
  [uint32 big-endian length][JSON payload bytes]

Expected JSON payload fields:
  sensor_id (str), train_id (str), timestamp_utc (str, ISO-8601),
  sequence_no (int), vibration_rms (float), vibration_kurtosis (float),
  temperature_bogie (float), wheel_load_left (float),
  wheel_load_right (float), acoustic_emission_rms (float),
  speed_kmh (float)

Dead-letter pattern (Task 3.4):
  - On 3 consecutive parse failures for the same source, emit
    ``LEGACY_ADAPTER_FAILURE`` to ``monitoring.alerts`` and route the raw
    payload to ``dead-letter.adapter-failures``.

Prometheus metrics (Task 3.5):
  - adapter_events_total{adapter_name="omrs", adapter_version=<VERSION>}
  - adapter_parse_failures_total{adapter_name="omrs"}
  - adapter_kafka_publish_errors_total{adapter_name="omrs"}
  Served on :8080/metrics.

Design §4.4 / Req 1 / Req 31 / Tasks 3.2, 3.4, 3.5
"""

from __future__ import annotations

import json
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
OMRS_HOST            = os.environ.get("OMRS_HOST", "omrs-stream.railos.svc.cluster.local")
OMRS_PORT            = int(os.environ.get("OMRS_PORT", "9001"))
KAFKA_BOOTSTRAP      = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
TELEMETRY_TOPIC      = "train.telemetry.omrs"
ADAPTER_NAME         = "omrs"
ADAPTER_VERSION      = os.environ.get("ADAPTER_VERSION", "1.0.0")
METRICS_PORT         = int(os.environ.get("METRICS_PORT", "8080"))
RECONNECT_DELAY_S    = float(os.environ.get("RECONNECT_DELAY_SECONDS", "5"))

# Length-prefix header: 4-byte unsigned int, big-endian
FRAME_HEADER_FORMAT  = ">I"
FRAME_HEADER_SIZE    = struct.calcsize(FRAME_HEADER_FORMAT)

configure_logging()
log = logging.getLogger("omrs-adapter")


# ── Kafka producer factory ─────────────────────────────────────────────────────

def make_producer() -> Any:
    return make_kafka_producer(bootstrap_servers=KAFKA_BOOTSTRAP)


# ── Frame I/O helpers ──────────────────────────────────────────────────────────

def read_frame(sock: socket.socket) -> bytes:
    """
    Read one length-prefixed frame from the OMRS TCP stream.

    Returns the raw payload bytes (without the 4-byte header).
    Raises EOFError if the connection is closed, socket.error on I/O error.
    """
    header = recv_exactly(sock, FRAME_HEADER_SIZE)
    (payload_len,) = struct.unpack(FRAME_HEADER_FORMAT, header)
    return recv_exactly(sock, payload_len)


# ── OMRS normalisation ─────────────────────────────────────────────────────────

def parse_omrs_frame(raw_payload: bytes) -> CanonicalEvent:
    """
    Decode a raw OMRS frame payload (JSON bytes) and return a CanonicalEvent.

    Expected JSON fields:
      sensor_id, train_id, timestamp_utc, sequence_no,
      vibration_rms, vibration_kurtosis, temperature_bogie,
      wheel_load_left, wheel_load_right, acoustic_emission_rms, speed_kmh

    Raises ValueError, KeyError, or json.JSONDecodeError on malformed input.
    """
    record: dict[str, Any] = json.loads(raw_payload.decode("utf-8"))

    sensor_id: str   = str(record["sensor_id"])
    train_id: str    = str(record["train_id"])
    ts: str          = str(record.get("timestamp_utc", datetime.now(timezone.utc).isoformat()))
    seq: int         = int(record.get("sequence_no", 0))

    # Normalised payload — all numeric fields are required
    vib_rms: float           = float(record["vibration_rms"])
    vib_kurtosis: float      = float(record["vibration_kurtosis"])
    temp_bogie: float        = float(record["temperature_bogie"])
    wl_left: float           = float(record["wheel_load_left"])
    wl_right: float          = float(record["wheel_load_right"])
    acoustic_rms: float      = float(record["acoustic_emission_rms"])
    speed: float             = float(record["speed_kmh"])

    return CanonicalEvent(
        eventId=str(uuid.uuid4()),
        sourceId=f"omrs-{sensor_id}",
        sensorType="wheel_load",
        assetId=f"loco-{train_id}",
        timestamp_utc=ts,
        sequence=seq,
        payload={
            "vibration_rms": vib_rms,
            "vibration_kurtosis": vib_kurtosis,
            "temperature_bogie": temp_bogie,
            "wheel_load_left": wl_left,
            "wheel_load_right": wl_right,
            "acoustic_emission_rms": acoustic_rms,
            "speed_kmh": speed,
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
    Main loop: connect to OMRS TCP server, read frames continuously.
    Reconnects automatically after any connection error.
    """
    log.info(
        "OMRS adapter started: host=%s port=%d topic=%s",
        OMRS_HOST,
        OMRS_PORT,
        TELEMETRY_TOPIC,
    )
    while True:
        try:
            _stream_until_disconnect(producer, metrics, router)
        except Exception as exc:
            log.error("OMRS stream error, reconnecting in %ss: %s", RECONNECT_DELAY_S, exc)
        time.sleep(RECONNECT_DELAY_S)


def _stream_until_disconnect(
    producer: Any,
    metrics: Any,
    router: DeadLetterRouter,
) -> None:
    """Open a single TCP connection and process frames until disconnect."""
    with socket.create_connection((OMRS_HOST, OMRS_PORT), timeout=30) as sock:
        log.info("Connected to OMRS at %s:%d", OMRS_HOST, OMRS_PORT)
        while True:
            try:
                raw_payload = read_frame(sock)
            except EOFError:
                log.warning("OMRS server closed connection")
                return
            except socket.error as exc:
                log.error("OMRS socket error: %s", exc)
                return

            source_id = "omrs-stream"
            try:
                event = parse_omrs_frame(raw_payload)
                source_id = event.sourceId
            except Exception as exc:
                log.warning("Failed to parse OMRS frame len=%d: %s", len(raw_payload), exc)
                metrics.parse_failures_total.inc()
                router.record_failure(source_id, raw_payload)
                continue

            router.reset(source_id)

            try:
                producer.send(TELEMETRY_TOPIC, value=event.to_kafka_message())
                producer.flush(timeout=5)
                metrics.events_total.inc()
                log.debug("Published OMRS event: source=%s seq=%d", event.sourceId, event.sequence)
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
