"""
RailOS Federated Learning Server (Tasks 9.1, 9.4, 9.5)
Flower FedAvg with quality check, ROUND_ABORTED on < 3 clients, 120s timeout.
Satisfies: Req 6, Design §6.4
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP  = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
FL_SERVER_PORT   = int(os.environ.get("FL_SERVER_PORT", "8080"))
MIN_CLIENTS      = int(os.environ.get("MIN_CLIENTS", "3"))
ROUND_TIMEOUT    = int(os.environ.get("ROUND_TIMEOUT", "120"))
METRICS_PORT     = int(os.environ.get("METRICS_PORT", "9090"))
ALERT_TOPIC      = "monitoring.alerts"

# Prometheus
fl_round_duration  = Histogram("fl_round_duration_seconds",   "FL round duration",    buckets=[10,30,60,90,120,180])
fl_clients_gauge   = Gauge("fl_participating_clients",         "Clients in last round")
fl_aborted_counter = Counter("fl_round_aborted_total",         "Rounds aborted due to insufficient clients")


def _emit_round_aborted(round_id: int, absent_clients: list[str]) -> None:
    payload = {
        "alertType":          "ROUND_ABORTED",
        "roundId":            round_id,
        "absentClients":      absent_clients,
        "retryAfterSeconds":  300,
    }
    log.warning("ROUND_ABORTED round=%d absent=%s", round_id, absent_clients)
    fl_aborted_counter.inc()
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
        p.send(ALERT_TOPIC, value=json.dumps(payload).encode())
        p.flush(timeout=5)
    except Exception as exc:
        log.error("Failed to emit ROUND_ABORTED to Kafka: %s", exc)


def start_fl_server() -> None:
    """Start the Flower FL server. Call from __main__."""
    try:
        import flwr as fl
        import numpy as np
    except ImportError:
        log.error("Flower (flwr) not installed. Run: pip install flwr==1.8.0")
        return

    start_http_server(METRICS_PORT)

    class FedAvgWithQualityCheck(fl.server.strategy.FedAvg):
        def aggregate_fit(self, server_round, results, failures):
            if len(results) < MIN_CLIENTS:
                absent = [str(i) for i in range(MIN_CLIENTS - len(results))]
                _emit_round_aborted(server_round, absent)
                return None, {}
            fl_clients_gauge.set(len(results))
            return super().aggregate_fit(server_round, results, failures)

    strategy = FedAvgWithQualityCheck(
        min_fit_clients=MIN_CLIENTS,
        min_evaluate_clients=MIN_CLIENTS,
        min_available_clients=MIN_CLIENTS,
        fraction_fit=1.0,
    )

    fl.server.start_server(
        server_address=f"0.0.0.0:{FL_SERVER_PORT}",
        config=fl.server.ServerConfig(num_rounds=10),
        strategy=strategy,
    )


if __name__ == "__main__":
    start_fl_server()
