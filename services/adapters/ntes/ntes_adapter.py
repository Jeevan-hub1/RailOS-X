"""
RailOS NTES REST Adapter (Task 3.1)
=====================================
Polls the National Train Enquiry System (NTES) HTTP API every 30 seconds,
normalises each train position record to a canonical ``train.telemetry.position``
event, and publishes it to Kafka.

Dead-letter pattern (Task 3.4):
  - On 3 consecutive parse failures for the same source payload, emit
    ``LEGACY_ADAPTER_FAILURE`` to ``monitoring.alerts`` and route the raw
    response to ``dead-letter.adapter-failures``.

Prometheus metrics (Task 3.5):
  - adapter_events_total{adapter_name="ntes", adapter_version=<ADAPTER_VERSION>}
  - adapter_parse_failures_total{adapter_name="ntes"}
  - adapter_kafka_publish_errors_total{adapter_name="ntes"}
  Served on :8080/metrics.

Design §4.4 / Req 1 / Tasks 3.1, 3.4, 3.5
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

# Add shared library to path when running as a standalone container
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

from shared.canonical_event import CanonicalEvent, QualityFlags
from shared.dead_letter import DeadLetterRouter
from shared.prometheus_metrics import make_metrics, start_metrics_server
from common.kafka_utils import make_kafka_producer, KafkaError
from common.logging_config import configure_logging

# ── Configuration ─────────────────────────────────────────────────────────────
NTES_API_URL         = os.environ.get("NTES_API_URL", "http://ntes-api.railos.svc.cluster.local")
KAFKA_BOOTSTRAP      = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
POLL_INTERVAL_S      = float(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
TELEMETRY_TOPIC      = "train.telemetry.position"
ADAPTER_NAME         = "ntes"
ADAPTER_VERSION      = os.environ.get("ADAPTER_VERSION", "1.0.0")
METRICS_PORT         = int(os.environ.get("METRICS_PORT", "8080"))

configure_logging()
log = logging.getLogger("ntes-adapter")


# ── Kafka producer factory ─────────────────────────────────────────────────────

def make_producer() -> Any:
    return make_kafka_producer(bootstrap_servers=KAFKA_BOOTSTRAP)


# ── NTES normalisation ─────────────────────────────────────────────────────────

def parse_ntes_record(record: dict[str, Any]) -> CanonicalEvent:
    """
    Normalise a single NTES train-position record to a canonical event.

    Expected NTES record fields:
      train_number (str), latitude (float), longitude (float),
      speed_kmh (float), station_code (str), timestamp (ISO str),
      sequence_no (int)

    Raises ValueError or KeyError on malformed input.
    """
    train_number: str = str(record["train_number"])
    lat: float = float(record["latitude"])
    lon: float = float(record["longitude"])
    speed: float = float(record.get("speed_kmh", 0.0))
    station: str = str(record.get("station_code", "UNKNOWN"))
    ts: str = str(record.get("timestamp", datetime.now(timezone.utc).isoformat()))
    seq: int = int(record.get("sequence_no", 0))

    return CanonicalEvent(
        eventId=str(uuid.uuid4()),
        sourceId=f"ntes-{train_number}",
        sensorType="gps",
        assetId=f"loco-{train_number}",
        timestamp_utc=ts,
        sequence=seq,
        payload={
            "latitude": lat,
            "longitude": lon,
            "speed_kmh": speed,
            "station_code": station,
        },
        quality_flags=QualityFlags(
            interpolated=False,
            interpolation_pct=0.0,
            clock_reliable=True,
            drift_ms=0.0,
        ),
        schema_version="1.0.0",
    )


# ── Polling loop ───────────────────────────────────────────────────────────────

def run_poll_loop(producer: Any, metrics: Any, router: DeadLetterRouter) -> None:
    """Main polling loop — runs until the process is terminated."""
    http_client = httpx.Client(timeout=10.0)
    log.info(
        "NTES adapter started: url=%s interval=%ss topic=%s",
        NTES_API_URL,
        POLL_INTERVAL_S,
        TELEMETRY_TOPIC,
    )

    while True:
        try:
            _poll_once(http_client, producer, metrics, router)
        except Exception as exc:
            log.error("Unexpected error in poll loop: %s", exc)
        time.sleep(POLL_INTERVAL_S)


def _poll_once(
    http_client: Any,
    producer: Any,
    metrics: Any,
    router: DeadLetterRouter,
) -> None:
    """Perform a single poll of the NTES API and publish all records."""
    url = f"{NTES_API_URL.rstrip('/')}/v1/train-positions"
    try:
        response = http_client.get(url)
        response.raise_for_status()
    except Exception as exc:
        log.error("NTES HTTP request failed: %s", exc)
        return

    raw_bytes = response.content

    try:
        records: list[dict[str, Any]] = response.json()
    except Exception:
        log.error("NTES response is not valid JSON")
        router.record_failure("ntes-api-response", raw_bytes)
        metrics.parse_failures_total.inc()
        return

    if not isinstance(records, list):
        log.error("NTES response root is not a list")
        router.record_failure("ntes-api-response", raw_bytes)
        metrics.parse_failures_total.inc()
        return

    for record in records:
        source_id = f"ntes-{record.get('train_number', 'unknown')}"
        try:
            event = parse_ntes_record(record)
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("Failed to parse NTES record source=%s: %s", source_id, exc)
            metrics.parse_failures_total.inc()
            router.record_failure(source_id, str(record).encode("utf-8"))
            continue

        # Successful parse — reset dead-letter counter
        router.reset(source_id)

        try:
            producer.send(TELEMETRY_TOPIC, value=event.to_kafka_message())
            producer.flush(timeout=5)
            metrics.events_total.inc()
            log.debug("Published event: source=%s seq=%d", event.sourceId, event.sequence)
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
    run_poll_loop(producer, metrics, router)


if __name__ == "__main__":
    main()
