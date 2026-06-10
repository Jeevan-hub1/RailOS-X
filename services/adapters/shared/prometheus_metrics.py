"""
RailOS Adapter Shared Prometheus Metrics (Task 3.5)
====================================================
Exposes three shared counters used by all legacy system adapters:

  - adapter_events_total{adapter_name, adapter_version}
  - adapter_parse_failures_total{adapter_name}
  - adapter_kafka_publish_errors_total{adapter_name}

The ``adapter_version`` label satisfies Task 3.5.

Usage::

    from shared.prometheus_metrics import make_metrics, start_metrics_server

    metrics = make_metrics(adapter_name="ntes", adapter_version="1.0.0")
    start_metrics_server(port=8080)

    metrics.events_total.inc()
    metrics.parse_failures_total.inc()
    metrics.kafka_publish_errors_total.inc()

Design §8 / Req 1 / Task 3.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from prometheus_client import Counter, start_http_server

log = logging.getLogger("prometheus-metrics")


@dataclass(frozen=True)
class AdapterMetrics:
    """Container for the three per-adapter Prometheus counters."""

    events_total: Counter
    parse_failures_total: Counter
    kafka_publish_errors_total: Counter


def make_metrics(adapter_name: str, adapter_version: str) -> AdapterMetrics:
    """
    Create (or retrieve) the three shared adapter Prometheus counters.

    Prometheus counters are process-global; calling this function multiple
    times with the same names is safe — the same Counter objects are returned.
    """
    # events_total carries adapter_version as an additional label (Task 3.5)
    events_total = Counter(
        "adapter_events_total",
        "Total number of events successfully published by the adapter",
        ["adapter_name", "adapter_version"],
    ).labels(adapter_name=adapter_name, adapter_version=adapter_version)

    parse_failures_total = Counter(
        "adapter_parse_failures_total",
        "Total number of payload parse failures encountered by the adapter",
        ["adapter_name"],
    ).labels(adapter_name=adapter_name)

    kafka_publish_errors_total = Counter(
        "adapter_kafka_publish_errors_total",
        "Total number of Kafka publish errors encountered by the adapter",
        ["adapter_name"],
    ).labels(adapter_name=adapter_name)

    return AdapterMetrics(
        events_total=events_total,
        parse_failures_total=parse_failures_total,
        kafka_publish_errors_total=kafka_publish_errors_total,
    )


def start_metrics_server(port: int = 8080) -> None:
    """Start the Prometheus HTTP metrics server on *port*."""
    start_http_server(port)
    log.info("Prometheus metrics server started on port %d", port)
