"""
RailOS Cybersecurity Anomaly Scorer (Tasks 12.2–12.4)
Rolling window SCADA consumer → LSTM reconstruction MSE → SECURITY_ANOMALY alert.
Forensic capture: raw 60s window → MinIO WORM bucket on every anomaly.
Satisfies: Req 9 C1–C4, Design §6.6
"""
from __future__ import annotations

import json
import logging
import os
import tarfile
import time
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional
import numpy as np
import torch
from prometheus_client import Counter, start_http_server

from .lstm_autoencoder import LSTMAutoencoder

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)

# ── Config ──────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP     = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                      "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
SCADA_TOPIC         = os.environ.get("SCADA_TOPIC",    "scada.traffic")
SECURITY_TOPIC      = "security.anomalies"
ALERT_TOPIC         = "monitoring.alerts"
MSE_THRESHOLD       = float(os.environ.get("MSE_THRESHOLD", "0.05"))
MODEL_PATH          = os.environ.get("MODEL_PATH", "/models/lstm_autoencoder_v1.0.0.pt")
MINIO_ENDPOINT      = os.environ.get("MINIO_ENDPOINT", "http://minio.railos.svc.cluster.local:9000")
MINIO_ACCESS_KEY    = os.environ.get("MINIO_ACCESS_KEY", "railos-admin")
MINIO_SECRET_KEY    = os.environ.get("MINIO_SECRET_KEY", "change-me")
FORENSIC_BUCKET     = os.environ.get("FORENSIC_BUCKET", "railos-forensic-evidence")
IEC62443_ZONE       = os.environ.get("IEC62443_ZONE", "Zone-2")
METRICS_PORT        = int(os.environ.get("METRICS_PORT", "8080"))

# Window: 60s, stride 10s → 50s overlap
WINDOW_SIZE = 60   # seconds = samples at 1Hz
STRIDE      = 10

# Prometheus
anomalies_detected  = Counter("security_anomalies_detected_total",  "SECURITY_ANOMALY alerts emitted")
forensic_captures   = Counter("forensic_captures_total",             "Forensic evidence archives written to MinIO")


class SCADAAnomalyDetector:
    """Consumes SCADA traffic, runs LSTM autoencoder, emits SECURITY_ANOMALY alerts."""

    def __init__(self) -> None:
        self._model: Optional[LSTMAutoencoder] = None
        self._window: list[list[float]] = []  # list of feature vectors
        self._raw_msgs: list[bytes] = []       # raw messages for forensic capture

    def load_model(self) -> None:
        if os.path.exists(MODEL_PATH):
            self._model = LSTMAutoencoder.load(MODEL_PATH)
            log.info("LSTM autoencoder loaded from %s", MODEL_PATH)
        else:
            self._model = LSTMAutoencoder()
            log.warning("Model path not found — using untrained autoencoder (dev mode)")

    def process_message(self, raw: bytes, features: list[float]) -> Optional[dict]:
        """Add a SCADA message to the rolling window; evaluate when window is full.

        Returns SECURITY_ANOMALY dict if anomaly detected, else None.
        """
        self._window.append(features)
        self._raw_msgs.append(raw)

        if len(self._window) < WINDOW_SIZE:
            return None

        # Evaluate current 60-sample window
        result = self._evaluate_window()

        # Slide: drop oldest STRIDE samples
        self._window    = self._window[STRIDE:]
        self._raw_msgs  = self._raw_msgs[STRIDE:]

        return result

    def _evaluate_window(self) -> Optional[dict]:
        if self._model is None:
            return None

        x = torch.tensor(
            [self._window[-WINDOW_SIZE:]],
            dtype=torch.float32,
        )  # (1, 60, n_features)

        mse = self._model.reconstruction_error(x)

        if mse > MSE_THRESHOLD:
            alert_id = str(uuid.uuid4())
            alert = {
                "alertId":          alert_id,
                "alertType":        "SECURITY_ANOMALY",
                "iec62443Zone":     IEC62443_ZONE,
                "timestamp_utc":    datetime.now(timezone.utc).isoformat(),
                "reconstructionError": round(mse, 6),
                "threshold":        MSE_THRESHOLD,
                "acknowledged":     False,
            }
            anomalies_detected.inc()
            log.warning("SECURITY_ANOMALY mse=%.6f threshold=%.6f zone=%s",
                        mse, MSE_THRESHOLD, IEC62443_ZONE)

            # Forensic capture (Task 12.4)
            self._capture_forensic_evidence(alert_id, alert, mse)

            return alert
        return None

    def _capture_forensic_evidence(
        self, alert_id: str, alert_meta: dict, recon_error: float
    ) -> None:
        """Write forensic evidence to MinIO WORM bucket (Task 12.4)."""
        try:
            import boto3
            from botocore.config import Config

            s3 = boto3.client(
                "s3",
                endpoint_url=MINIO_ENDPOINT,
                aws_access_key_id=MINIO_ACCESS_KEY,
                aws_secret_access_key=MINIO_SECRET_KEY,
                config=Config(signature_version="s3v4"),
            )

            # Build tarball in-memory
            buf = BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                # 1. Raw traffic window (PCAP stub: JSON-encoded messages)
                raw_json = json.dumps([m.decode("utf-8", errors="replace")
                                       for m in self._raw_msgs[-WINDOW_SIZE:]]).encode()
                _add_bytes_to_tar(tar, "raw_traffic_window.json", raw_json)

                # 2. Reconstruction error vector stub
                err_vec = json.dumps({"reconstruction_mse": recon_error}).encode()
                _add_bytes_to_tar(tar, "reconstruction_error_vector.json", err_vec)

                # 3. Alert metadata
                meta_bytes = json.dumps(alert_meta, indent=2).encode()
                _add_bytes_to_tar(tar, "alert_metadata.json", meta_bytes)

            buf.seek(0)
            key = f"{alert_id}.tar.gz"
            s3.put_object(Bucket=FORENSIC_BUCKET, Key=key, Body=buf.read())
            forensic_captures.inc()
            log.info("Forensic evidence captured: s3://%s/%s", FORENSIC_BUCKET, key)

        except Exception as exc:
            log.error("Forensic capture failed (non-fatal): %s", exc)


def _add_bytes_to_tar(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tar.addfile(info, BytesIO(data))


def run_consumer_loop() -> None:
    """Main consumer loop. Blocking."""
    start_http_server(METRICS_PORT)
    detector = SCADAAnomalyDetector()
    detector.load_model()

    try:
        from kafka import KafkaConsumer, KafkaProducer
    except ImportError:
        log.error("kafka-python not installed")
        return

    producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
    consumer = KafkaConsumer(
        SCADA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="cybersecurity-monitor",
        auto_offset_reset="latest",
    )

    for msg in consumer:
        raw = msg.value
        # Parse features from raw SCADA message (stub: use zeros if unparseable)
        try:
            record = json.loads(raw)
            features = [
                float(record.get("packet_rate", 0)),
                float(record.get("query_type_dist", 0)),
                float(record.get("inter_arrival_ms", 0)),
                float(record.get("payload_size", 0)),
                float(record.get("src_ip_entropy", 0)),
            ]
        except Exception as exc:
            log.warning("SCADA feature extraction failed, using zeros: %s", exc)
            features = [0.0] * LSTMAutoencoder.N_FEATURES

        alert = detector.process_message(raw, features)
        if alert:
            # Publish to security.anomalies and monitoring.alerts
            alert_bytes = json.dumps(alert).encode()
            producer.send(SECURITY_TOPIC, value=alert_bytes)
            producer.send(ALERT_TOPIC, value=alert_bytes)
            producer.flush(timeout=5)


if __name__ == "__main__":
    run_consumer_loop()
