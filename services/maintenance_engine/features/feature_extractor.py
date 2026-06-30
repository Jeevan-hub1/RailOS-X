"""
RailOS Predictive Maintenance Engine — Feature Extractor (Task 7.1)

Kafka consumer that subscribes to OMRS and WILD telemetry topics, maintains
a per-asset 30-minute rolling window of 8 features at 1 Hz (1800 timesteps),
and publishes completed windows to ``train.features.maintenance``.

Field mapping
-------------
OMRS payload  (``train.telemetry.omrs``)
  bearing_rms_g       → vibration_rms          (feature index 0)
  bearing_kurtosis    → vibration_kurtosis      (feature index 1)
  bearing_peak_g      → vibration_peak          (feature index 2)
  bogie_temp_c        → temperature_bogie       (feature index 3)
  acoustic_rms        → acoustic_emission_rms   (feature index 6)
  speed_kmh           → speed_kmh               (feature index 7)
  (wheel loads default to 0.0 when not present in OMRS payload)

WILD payload  (``train.telemetry.wild``)
  wheel_load_left_kn  → wheel_load_left         (feature index 4)
  wheel_load_right_kn → wheel_load_right        (feature index 5)
  speed_kmh           → speed_kmh               (feature index 7)
  (vibration / temperature / acoustic default to 0.0 when not in WILD payload)

Feature vector order (matches MaintenanceLSTM.FEATURES):
  [vibration_rms, vibration_kurtosis, vibration_peak,
   temperature_bogie, wheel_load_left, wheel_load_right,
   acoustic_emission_rms, speed_kmh]

Gap handling
------------
If a timestep gap > 5 minutes is detected between successive readings for an
asset, linear interpolation is used to fill the missing timesteps.
``interpolation_pct`` tracks the percentage of the 1800 timestep window that
was filled via interpolation.

Window emission (on every 30-minute boundary)
---------------------------------------------------
* interpolation_pct > 40% → publish INSUFFICIENT_DATA to ``maintenance.advisories``
* otherwise → publish feature window JSON to ``train.features.maintenance``

Prometheus metrics
------------------
``feature_windows_emitted_total{asset_id}``    — successful feature windows published
``insufficient_data_windows_total``            — windows discarded due to poor data quality

Satisfies: Req 4 C1, C4, C5; Design §6.2
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional

import numpy as np
from prometheus_client import Counter, start_http_server

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
OMRS_TOPIC: str = "train.telemetry.omrs"
WILD_TOPIC: str = "train.telemetry.wild"
FEATURES_TOPIC: str = "train.features.maintenance"
ADVISORIES_TOPIC: str = "maintenance.advisories"

PROMETHEUS_PORT: int = int(os.getenv("PROMETHEUS_PORT", "9091"))

# Window configuration
WINDOW_SIZE: int = 1800            # 30 minutes × 1 Hz = 1800 timesteps
N_FEATURES: int = 8                # feature vector length
MAX_GAP_SECONDS: float = 300.0     # 5-minute gap → interpolate
INSUFFICIENT_DATA_THRESHOLD: float = 40.0  # % interpolated to discard window

# ---------------------------------------------------------------------------
# Feature indices (must match MaintenanceLSTM.FEATURES order)
# ---------------------------------------------------------------------------
IDX_VIBRATION_RMS = 0
IDX_VIBRATION_KURTOSIS = 1
IDX_VIBRATION_PEAK = 2
IDX_TEMPERATURE_BOGIE = 3
IDX_WHEEL_LOAD_LEFT = 4
IDX_WHEEL_LOAD_RIGHT = 5
IDX_ACOUSTIC_EMISSION_RMS = 6
IDX_SPEED_KMH = 7

# ---------------------------------------------------------------------------
# OMRS field → feature index mapping
# ---------------------------------------------------------------------------
OMRS_FIELD_MAP: dict[str, int] = {
    "bearing_rms_g":    IDX_VIBRATION_RMS,
    "bearing_kurtosis": IDX_VIBRATION_KURTOSIS,
    "bearing_peak_g":   IDX_VIBRATION_PEAK,
    "bogie_temp_c":     IDX_TEMPERATURE_BOGIE,
    "acoustic_rms":     IDX_ACOUSTIC_EMISSION_RMS,
    "speed_kmh":        IDX_SPEED_KMH,
}

# ---------------------------------------------------------------------------
# WILD field → feature index mapping
# ---------------------------------------------------------------------------
WILD_FIELD_MAP: dict[str, int] = {
    "wheel_load_left_kn":  IDX_WHEEL_LOAD_LEFT,
    "wheel_load_right_kn": IDX_WHEEL_LOAD_RIGHT,
    "speed_kmh":           IDX_SPEED_KMH,
}

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
FEATURE_WINDOWS_EMITTED = Counter(
    "railos_feature_windows_emitted_total",
    "Total feature windows published to train.features.maintenance",
    ["asset_id"],
)
INSUFFICIENT_DATA_WINDOWS = Counter(
    "railos_insufficient_data_windows_total",
    "Total windows discarded due to high interpolation percentage",
)


# ---------------------------------------------------------------------------
# Per-asset rolling window state
# ---------------------------------------------------------------------------
class AssetWindow:
    """Maintains a 1800-timestep rolling feature buffer for one asset.

    Each entry in the buffer is a tuple (timestamp_utc_seconds: float,
    feature_vector: np.ndarray[8]).  The buffer is ordered by ascending
    timestamp.
    """

    def __init__(self, asset_id: str) -> None:
        self.asset_id: str = asset_id
        # Deque of (timestamp_s, feature_vec) tuples
        self.buffer: Deque[tuple[float, np.ndarray]] = deque(maxlen=WINDOW_SIZE)
        # Count of timesteps filled by interpolation in the current window
        self.interpolated_count: int = 0
        # Lock for thread-safe access when the consumer loop runs in a thread
        self.lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest(self, timestamp_s: float, raw_features: np.ndarray) -> None:
        """Add a new timestep, interpolating if the gap > MAX_GAP_SECONDS.

        Args:
            timestamp_s:  Unix timestamp (seconds) of the new reading.
            raw_features: np.ndarray of shape (8,) — zero-padded for absent fields.
        """
        with self.lock:
            if len(self.buffer) == 0:
                self.buffer.append((timestamp_s, raw_features.copy()))
                return

            last_ts, last_vec = self.buffer[-1]
            gap = timestamp_s - last_ts

            if gap <= 0:
                # Out-of-order or duplicate; skip silently
                return

            if gap > MAX_GAP_SECONDS:
                # Interpolate missing timesteps
                n_missing = min(int(round(gap)) - 1, WINDOW_SIZE - 1)
                if n_missing > 0:
                    for step in range(1, n_missing + 1):
                        alpha = step / (n_missing + 1)
                        interp_vec = (1.0 - alpha) * last_vec + alpha * raw_features
                        interp_ts = last_ts + step * (gap / (n_missing + 1))
                        self.buffer.append((interp_ts, interp_vec.astype(np.float32)))
                        self.interpolated_count += 1

            self.buffer.append((timestamp_s, raw_features.copy()))

    def is_full(self) -> bool:
        """Return True when the buffer holds exactly WINDOW_SIZE timesteps."""
        return len(self.buffer) == WINDOW_SIZE

    def extract_window(self) -> tuple[np.ndarray, float]:
        """Extract the current window as a 2-D array and return interpolation %.

        Returns:
            (features_2d, interpolation_pct)
            features_2d : np.ndarray of shape (1800, 8), dtype float32
            interpolation_pct : float in [0.0, 100.0]
        """
        with self.lock:
            vecs = [vec for _, vec in self.buffer]
            features_2d = np.array(vecs, dtype=np.float32)  # (1800, 8)
            interp_pct = (self.interpolated_count / WINDOW_SIZE) * 100.0
            # Reset state for the next window
            self.buffer.clear()
            self.interpolated_count = 0
            return features_2d, interp_pct


# ---------------------------------------------------------------------------
# Payload field extraction helpers
# ---------------------------------------------------------------------------
def _extract_omrs_features(payload: dict) -> np.ndarray:
    """Map an OMRS canonical event payload to an 8-element feature vector.

    Missing OMRS-specific fields default to 0.0.  ``speed_kmh`` is taken
    from the payload's top-level ``speed_kmh`` key if present.

    Args:
        payload: Dict from the ``train.telemetry.omrs`` Kafka message.

    Returns:
        np.ndarray of shape (8,), dtype float32.
    """
    vec = np.zeros(N_FEATURES, dtype=np.float32)
    for field, idx in OMRS_FIELD_MAP.items():
        val = payload.get(field)
        if val is not None:
            vec[idx] = float(val)
    return vec


def _extract_wild_features(payload: dict) -> np.ndarray:
    """Map a WILD canonical event payload to an 8-element feature vector.

    Only wheel load fields and speed are populated; vibration/acoustic/temp
    default to 0.0 as they are not measured by WILD sensors.

    Args:
        payload: Dict from the ``train.telemetry.wild`` Kafka message.

    Returns:
        np.ndarray of shape (8,), dtype float32.
    """
    vec = np.zeros(N_FEATURES, dtype=np.float32)
    for field, idx in WILD_FIELD_MAP.items():
        val = payload.get(field)
        if val is not None:
            vec[idx] = float(val)
    return vec


def _parse_timestamp(ts_str: str) -> float:
    """Parse ISO 8601 UTC timestamp string to Unix epoch seconds.

    Falls back to current time if parsing fails.
    """
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        log.warning("Could not parse timestamp '%s'; using current time.", ts_str)
        return time.time()


# ---------------------------------------------------------------------------
# Feature Extractor — main service class
# ---------------------------------------------------------------------------
class FeatureExtractor:
    """Consumes OMRS and WILD Kafka messages, builds per-asset rolling windows,
    and emits feature windows or INSUFFICIENT_DATA advisories.
    """

    def __init__(self) -> None:
        self._windows: Dict[str, AssetWindow] = {}
        self._producer: Any = None
        self._consumer: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def startup(self) -> None:
        """Start Prometheus server and connect Kafka clients."""
        try:
            start_http_server(PROMETHEUS_PORT)
            log.info("Prometheus metrics server started on port %d", PROMETHEUS_PORT)
        except OSError:
            log.warning("Prometheus port %d already in use; skipping.", PROMETHEUS_PORT)

        self._setup_kafka()
        log.info("FeatureExtractor started, consuming from %s + %s", OMRS_TOPIC, WILD_TOPIC)

    def _setup_kafka(self) -> None:
        """Initialise KafkaProducer and KafkaConsumer (graceful if unavailable)."""
        try:
            from kafka import KafkaConsumer, KafkaProducer  # type: ignore[import]

            self._producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=5,
            )
            self._consumer = KafkaConsumer(
                OMRS_TOPIC,
                WILD_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS.split(","),
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
                group_id="feature-extractor",
                auto_offset_reset="latest",
                enable_auto_commit=True,
            )
            log.info("Kafka connected to %s", KAFKA_BOOTSTRAP_SERVERS)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Kafka unavailable (%s); running in dev/test mode without message bus.", exc
            )

    def shutdown(self) -> None:
        """Close Kafka clients gracefully."""
        if self._consumer:
            try:
                self._consumer.close()
            except Exception:  # noqa: BLE001
                pass
        if self._producer:
            try:
                self._producer.flush(timeout=5)
                self._producer.close()
            except Exception:  # noqa: BLE001
                pass
        log.info("FeatureExtractor shut down.")

    # ------------------------------------------------------------------
    # Message ingestion
    # ------------------------------------------------------------------
    def process_message(self, topic: str, message_value: dict) -> Optional[dict]:
        """Process a single Kafka message and emit a window if the buffer is full.

        Args:
            topic:         Kafka topic name (``train.telemetry.omrs`` or ``train.telemetry.wild``).
            message_value: Decoded message dict (canonical sensor event schema).

        Returns:
            Published payload dict if a window was emitted, or None.
        """
        asset_id: str = message_value.get("assetId", "unknown")
        timestamp_str: str = message_value.get("timestamp_utc", "")
        timestamp_s: float = _parse_timestamp(timestamp_str) if timestamp_str else time.time()

        # Extract feature vector based on topic
        payload = message_value.get("payload", message_value)
        if topic == OMRS_TOPIC:
            raw_features = _extract_omrs_features(payload)
        elif topic == WILD_TOPIC:
            raw_features = _extract_wild_features(payload)
        else:
            log.warning("Unknown topic '%s'; skipping message.", topic)
            return None

        # Get or create per-asset window state
        if asset_id not in self._windows:
            self._windows[asset_id] = AssetWindow(asset_id)

        window = self._windows[asset_id]
        window.ingest(timestamp_s, raw_features)

        # Emit window when full
        if window.is_full():
            return self._emit_window(asset_id, window, timestamp_str or _now_iso())

        return None

    def _emit_window(
        self,
        asset_id: str,
        window: AssetWindow,
        timestamp_utc: str,
    ) -> dict:
        """Extract window data and publish to the appropriate topic.

        Args:
            asset_id:       Asset identifier.
            window:         AssetWindow whose buffer is full.
            timestamp_utc:  ISO 8601 timestamp of the triggering message.

        Returns:
            Published payload dict.
        """
        features_2d, interp_pct = window.extract_window()

        if interp_pct > INSUFFICIENT_DATA_THRESHOLD:
            # Poor data quality — emit INSUFFICIENT_DATA advisory
            advisory = {
                "alertId":        _new_uuid(),
                "alertType":      "INSUFFICIENT_DATA",
                "timestamp_utc":  timestamp_utc,
                "assetId":        asset_id,
                "dataQualityPct": round(interp_pct, 2),
            }
            self._publish(ADVISORIES_TOPIC, advisory)
            INSUFFICIENT_DATA_WINDOWS.inc()
            log.warning(
                "INSUFFICIENT_DATA for asset %s: interpolation_pct=%.1f%%",
                asset_id,
                interp_pct,
            )
            return advisory
        else:
            # Good data — emit feature window for inference
            window_payload = {
                "asset_id":         asset_id,
                "features":         features_2d.tolist(),
                "interpolation_pct": round(interp_pct, 2),
                "timestamp_utc":    timestamp_utc,
            }
            self._publish(FEATURES_TOPIC, window_payload)
            FEATURE_WINDOWS_EMITTED.labels(asset_id=asset_id).inc()
            log.info(
                "Feature window emitted for asset %s (interpolation_pct=%.1f%%)",
                asset_id,
                interp_pct,
            )
            return window_payload

    # ------------------------------------------------------------------
    # Consumer loop
    # ------------------------------------------------------------------
    def run_consumer_loop(self) -> None:
        """Blocking Kafka consumer loop. Intended to run in a background thread."""
        if self._consumer is None:
            log.error("Kafka consumer not initialised; cannot start consumer loop.")
            return
        log.info(
            "FeatureExtractor consumer loop started on topics %s + %s",
            OMRS_TOPIC,
            WILD_TOPIC,
        )
        for msg in self._consumer:
            try:
                self.process_message(msg.topic, msg.value)
            except Exception as exc:  # noqa: BLE001
                log.exception("Error processing message from %s: %s", msg.topic, exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _publish(self, topic: str, payload: dict) -> None:
        """Publish a JSON payload to a Kafka topic."""
        if self._producer is None:
            log.debug("No Kafka producer; skipping publish to %s", topic)
            return
        try:
            self._producer.send(topic, value=payload)
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to publish to %s: %s", topic, exc)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    import uuid
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Entry point (standalone process)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    extractor = FeatureExtractor()
    extractor.startup()
    try:
        extractor.run_consumer_loop()
    except KeyboardInterrupt:
        pass
    finally:
        extractor.shutdown()
