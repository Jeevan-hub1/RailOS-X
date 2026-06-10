"""
RailOS Clock Monitor
=====================
Monitors system clock drift against PTP reference. When drift exceeds
±DRIFT_THRESHOLD_MS milliseconds:
  - Publishes CLOCK_DRIFT_ALERT to monitoring.alerts Kafka topic (Task 2.3)
  - Sets clock_reliable=False flag injected into sensor event schema (Task 2.4)

The flag is exposed via a shared Redis key so sensor adapters can read it
without a direct dependency on this service.

Design §3.2: max permitted drift ±100ms from UTC reference.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import time
import uuid
from datetime import datetime, timezone

# Kafka import — guarded so unit tests run without kafka-python on Windows dev machines.
try:
    from kafka import KafkaProducer
    from kafka.errors import KafkaError
except Exception:  # pragma: no cover — kafka not available in unit-test environment
    KafkaProducer = None  # type: ignore[assignment,misc]
    KafkaError = Exception  # type: ignore[assignment,misc]

# adjtimex / libc.so.6 is Linux-only.  Guard for cross-platform test compatibility.
if platform.system() == "Linux":
    from ctypes import CDLL, c_int, c_long, Structure, byref as _byref
    _libc_available = True
else:
    _libc_available = False
    # Stub types so the module loads on Windows (tests mock get_clock_drift_ms anyway)
    class _StubStructure:
        pass
    Structure = _StubStructure  # type: ignore
    CDLL = None  # type: ignore

# ── Configuration ──────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP    = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
DRIFT_THRESHOLD_MS = float(os.environ.get("DRIFT_THRESHOLD_MS", "100"))
POLL_INTERVAL_S    = float(os.environ.get("POLL_INTERVAL_S", "1"))
NODE_ID            = os.environ.get("NODE_ID", "zone-compute-01")
ALERT_TOPIC        = "monitoring.alerts"
CLOCK_STATUS_PATH  = os.environ.get("CLOCK_STATUS_PATH", "/tmp/railos_clock_reliable")

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("clock-monitor")


# ── Clock drift measurement ────────────────────────────────────────────────────

if _libc_available:
    from ctypes import CDLL, c_int, c_long, Structure, byref as _byref

    class Timex(Structure):
        """Linux struct timex (from <sys/timex.h>) for adjtimex() syscall."""
        _fields_ = [
            ("modes",     c_int),
            ("offset",    c_long),
            ("freq",      c_long),
            ("maxerror",  c_long),
            ("esterror",  c_long),
            ("status",    c_int),
            ("constant",  c_long),
            ("precision", c_long),
            ("tolerance", c_long),
            ("time_tv_sec",  c_long),
            ("time_tv_usec", c_long),
            ("tick",      c_long),
            ("ppsfreq",   c_long),
            ("jitter",    c_long),
            ("shift",     c_int),
            ("stabil",    c_long),
            ("jitcnt",    c_long),
            ("calcnt",    c_long),
            ("errcnt",    c_long),
            ("stbcnt",    c_long),
            ("tai",       c_int),
        ]

    _libc_handle = CDLL("libc.so.6")
    STA_UNSYNC = 0x0040

    def get_clock_drift_ms() -> tuple[float, bool]:
        tx = Timex()
        _libc_handle.adjtimex(_byref(tx))
        clock_reliable = not bool(tx.status & STA_UNSYNC)
        offset_ms = tx.offset / 1_000_000.0
        return offset_ms, clock_reliable

else:
    # Stub for non-Linux environments — replaced by mock in tests
    def get_clock_drift_ms() -> tuple[float, bool]:  # pragma: no cover
        raise NotImplementedError("adjtimex() is only available on Linux")


# ── Kafka producer ─────────────────────────────────────────────────────────────

def make_producer() -> object:
    if KafkaProducer is None:
        raise RuntimeError("kafka-python is not installed")
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",
        retries=3,
        retry_backoff_ms=500,
    )


def publish_drift_alert(producer: KafkaProducer, offset_ms: float) -> None:
    """Publish CLOCK_DRIFT_ALERT to monitoring.alerts (Task 2.3)."""
    event = {
        "eventId":      str(uuid.uuid4()),
        "alertType":    "CLOCK_DRIFT_ALERT",
        "sourceId":     NODE_ID,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "drift_ms":     offset_ms,
        "threshold_ms": DRIFT_THRESHOLD_MS,
        "severity":     "WARNING",
    }
    try:
        producer.send(ALERT_TOPIC, value=event)
        producer.flush(timeout=5)
        log.warning(f"CLOCK_DRIFT_ALERT published: drift={offset_ms:.2f}ms")
    except KafkaError as exc:
        log.error(f"Failed to publish CLOCK_DRIFT_ALERT: {exc}")


def publish_unreliable_event(producer: KafkaProducer) -> None:
    """Publish event signalling clock sync is lost (Task 2.4)."""
    event = {
        "eventId":      str(uuid.uuid4()),
        "alertType":    "CLOCK_SYNC_LOST",
        "sourceId":     NODE_ID,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "clock_reliable": False,
        "message":      "PTP sync lost — all subsequent sensor events carry CLOCK_UNRELIABLE flag",
    }
    try:
        producer.send(ALERT_TOPIC, value=event)
        producer.flush(timeout=5)
        log.error("CLOCK_SYNC_LOST published — CLOCK_UNRELIABLE flag active")
    except KafkaError as exc:
        log.error(f"Failed to publish CLOCK_SYNC_LOST: {exc}")


# ── Shared flag file ───────────────────────────────────────────────────────────
# Sensor adapters running in the same pod read this file to determine whether
# to set clock_reliable=False in the canonical sensor event schema (Task 2.4).

def write_clock_status(reliable: bool) -> None:
    """Write clock reliability flag to a well-known path for sensor adapters."""
    status = {"clock_reliable": reliable, "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        with open(CLOCK_STATUS_PATH, "w") as f:
            json.dump(status, f)
    except OSError as exc:
        log.error(f"Failed to write clock status: {exc}")


def read_clock_status() -> bool:
    """Read current clock reliability flag (used by sensor adapters)."""
    try:
        with open(CLOCK_STATUS_PATH) as f:
            return json.load(f).get("clock_reliable", True)
    except (OSError, json.JSONDecodeError):
        return True   # assume reliable if file missing (safe default)


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    log.info(f"Clock monitor starting: node={NODE_ID}, threshold=±{DRIFT_THRESHOLD_MS}ms, poll={POLL_INTERVAL_S}s")
    producer = make_producer()
    prev_reliable = True
    alert_cooldown = 0   # seconds remaining before next alert is sent

    while True:
        try:
            offset_ms, clock_reliable = get_clock_drift_ms()
            abs_drift = abs(offset_ms)

            # Detect reliability state change
            if not clock_reliable and prev_reliable:
                publish_unreliable_event(producer)
                write_clock_status(False)
            elif clock_reliable and not prev_reliable:
                log.info("Clock sync restored — CLOCK_UNRELIABLE flag cleared")
                write_clock_status(True)
            prev_reliable = clock_reliable

            # Drift threshold exceeded → send alert (with cooldown to avoid flooding)
            if clock_reliable and abs_drift > DRIFT_THRESHOLD_MS:
                if alert_cooldown <= 0:
                    publish_drift_alert(producer, offset_ms)
                    alert_cooldown = 60   # re-arm after 60s
                else:
                    log.warning(f"Drift {offset_ms:.2f}ms exceeds threshold (alert cooldown {alert_cooldown}s)")
            else:
                log.debug(f"Clock OK: drift={offset_ms:.3f}ms, reliable={clock_reliable}")

            if alert_cooldown > 0:
                alert_cooldown -= POLL_INTERVAL_S

        except Exception as exc:
            log.error(f"Clock monitor error: {exc}")

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
