#!/bin/bash
# entrypoint.sh — selects streamer or receiver mode based on ROLE env var
set -euo pipefail

ROLE="${ROLE:-streamer}"
METRICS_PORT="${METRICS_PORT:-9090}"

echo "[entrypoint] Starting InfluxDB WAL sidecar in role: ${ROLE}"

# Start the Prometheus metrics HTTP server in the background
echo "[entrypoint] Starting metrics server on port ${METRICS_PORT}..."
python3 /opt/wal-streamer/metrics.py "${METRICS_PORT}" &
METRICS_PID=$!

# Trap signals for graceful shutdown
trap 'echo "[entrypoint] Shutting down..."; kill "${METRICS_PID}" 2>/dev/null; exit 0' SIGTERM SIGINT

case "${ROLE}" in
  streamer)
    echo "[entrypoint] Launching WAL streamer..."
    exec /opt/wal-streamer/wal-stream.sh
    ;;
  receiver)
    echo "[entrypoint] Launching WAL receiver..."
    exec /opt/wal-streamer/wal-receive.sh
    ;;
  *)
    echo "[entrypoint] ERROR: Unknown ROLE '${ROLE}'. Must be 'streamer' or 'receiver'."
    exit 1
    ;;
esac
