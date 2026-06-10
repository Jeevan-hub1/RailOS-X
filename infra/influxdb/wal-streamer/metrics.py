#!/usr/bin/env python3
"""
metrics.py — Prometheus metrics HTTP server for WAL streamer/receiver sidecars.

Exposes the following metrics on /metrics:
  influxdb_replication_lag_seconds        — current WAL replication lag
  influxdb_wal_segments_received_total    — total WAL segments received (receiver only)
  influxdb_replication_connected          — 1 if replication connection is active

Also exposes /ready and /live endpoints for Kubernetes health probes.

Usage: python3 metrics.py <port>
"""
import sys
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST

# ─── Metrics ──────────────────────────────────────────────────────────────────

REPLICATION_LAG = Gauge(
    'influxdb_replication_lag_seconds',
    'Current WAL replication lag in seconds between primary and standby',
    ['role']
)

WAL_SEGMENTS_RECEIVED = Counter(
    'influxdb_wal_segments_received_total',
    'Total number of WAL segments received by the standby',
    ['role']
)

REPLICATION_CONNECTED = Gauge(
    'influxdb_replication_connected',
    '1 if the WAL replication connection is active, 0 otherwise',
    ['role']
)

# ─── File paths written by shell scripts ──────────────────────────────────────

LAG_FILE = '/tmp/replication_lag_seconds'
SEGMENTS_FILE = '/tmp/segments_received_total'

ROLE = os.environ.get('ROLE', 'streamer')

# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class MetricsHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Suppress default access log — we use structured logging

    def do_GET(self):
        if self.path == '/metrics':
            self._serve_metrics()
        elif self.path in ('/ready', '/live', '/healthz'):
            self._serve_health()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_metrics(self):
        # Read lag from file written by the shell script
        try:
            with open(LAG_FILE) as f:
                lag = float(f.read().strip())
        except (FileNotFoundError, ValueError):
            lag = 0.0

        # Read segment count from file
        try:
            with open(SEGMENTS_FILE) as f:
                segments = float(f.read().strip())
        except (FileNotFoundError, ValueError):
            segments = 0.0

        # Update gauges
        REPLICATION_LAG.labels(role=ROLE).set(lag)
        WAL_SEGMENTS_RECEIVED.labels(role=ROLE)  # ensure label set exists

        # Consider connected if lag is not the sentinel error value (999)
        REPLICATION_CONNECTED.labels(role=ROLE).set(0 if lag >= 999 else 1)

        output = generate_latest()
        self.send_response(200)
        self.send_header('Content-Type', CONTENT_TYPE_LATEST)
        self.send_header('Content-Length', str(len(output)))
        self.end_headers()
        self.wfile.write(output)

    def _serve_health(self):
        # Healthy unless lag is the sentinel error value
        try:
            with open(LAG_FILE) as f:
                lag = float(f.read().strip())
        except (FileNotFoundError, ValueError):
            lag = 0.0

        if lag >= 999:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'replication error')
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9090
    server = HTTPServer(('0.0.0.0', port), MetricsHandler)
    print(f'[metrics] Prometheus metrics server listening on :{port}', flush=True)
    print(f'[metrics] Role: {ROLE}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('[metrics] Shutting down.', flush=True)
