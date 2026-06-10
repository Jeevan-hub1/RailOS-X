#!/bin/bash
# wal-stream.sh — WAL Streamer (primary sidecar)
#
# Watches the primary InfluxDB WAL directory for new segment files.
# When a new segment is detected, it is forwarded to the standby via TCP.
# Replication lag is tracked and exported as a Prometheus metric.
#
# Environment variables (all required; set in the StatefulSet):
#   WAL_DIR                          — path to InfluxDB WAL directory
#   STANDBY_HOST                     — DNS name of standby WAL receiver
#   STANDBY_PORT                     — TCP port for WAL receiver (default 8088)
#   REPLICATION_LAG_THRESHOLD_SECONDS — lag alert threshold (default 60)
#   REPLICATION_SECRET               — shared secret for HMAC authentication
#   METRICS_PORT                     — port for Prometheus metrics (default 9090)
set -euo pipefail

WAL_DIR="${WAL_DIR:-/var/lib/influxdb3/wal}"
STANDBY_HOST="${STANDBY_HOST:?STANDBY_HOST must be set}"
STANDBY_PORT="${STANDBY_PORT:-8088}"
LAG_THRESHOLD="${REPLICATION_LAG_THRESHOLD_SECONDS:-60}"
REPLICATION_SECRET="${REPLICATION_SECRET:?REPLICATION_SECRET must be set}"
LAG_FILE="/tmp/replication_lag_seconds"
CURSOR_FILE="/tmp/wal_stream_cursor"

echo "[wal-streamer] Watching WAL directory: ${WAL_DIR}"
echo "[wal-streamer] Streaming to: ${STANDBY_HOST}:${STANDBY_PORT}"

# Initialize lag metric file (read by metrics.py)
echo "0" > "${LAG_FILE}"

# Track which WAL segments have been sent to avoid duplicates
touch "${CURSOR_FILE}"

send_segment() {
  local segment_file="$1"
  local segment_name
  segment_name=$(basename "${segment_file}")
  local send_start
  send_start=$(date +%s)

  echo "[wal-streamer] Sending WAL segment: ${segment_name}"

  # Compute HMAC for authentication (shared secret, prevents unauthorized writes to standby)
  local hmac
  hmac=$(echo -n "${segment_name}:${REPLICATION_SECRET}" | sha256sum | awk '{print $1}')

  # Send: header line (segment name + HMAC + file size) followed by binary content
  local file_size
  file_size=$(stat -c '%s' "${segment_file}")

  {
    echo "WAL-SEGMENT:${segment_name}:${file_size}:${hmac}"
    cat "${segment_file}"
  } | ncat --send-only "${STANDBY_HOST}" "${STANDBY_PORT}" --idle-timeout 30

  local send_end
  send_end=$(date +%s)
  local lag=$(( send_end - send_start ))

  # Update lag metric file (metrics.py reads this for the Prometheus gauge)
  echo "${lag}" > "${LAG_FILE}"

  if [ "${lag}" -gt "${LAG_THRESHOLD}" ]; then
    echo "[wal-streamer] WARNING: Replication lag ${lag}s exceeds threshold ${LAG_THRESHOLD}s"
  fi

  # Record that this segment has been sent
  echo "${segment_name}" >> "${CURSOR_FILE}"
  echo "[wal-streamer] Sent ${segment_name} (lag: ${lag}s)"
}

# Main loop: watch for new WAL segment files
echo "[wal-streamer] Entering inotifywait watch loop..."
inotifywait -m -e close_write -e moved_to --format '%f' "${WAL_DIR}" | while read -r filename; do
  # Only process .wal segment files
  if [[ "${filename}" =~ \.wal$ ]]; then
    full_path="${WAL_DIR}/${filename}"
    # Skip if already sent (handles inotify re-delivery on reconnect)
    if grep -qxF "${filename}" "${CURSOR_FILE}" 2>/dev/null; then
      echo "[wal-streamer] Skipping already-sent segment: ${filename}"
      continue
    fi
    send_segment "${full_path}" || {
      echo "[wal-streamer] ERROR: Failed to send segment ${filename}. Will retry on reconnect."
      # Update lag to a large value to trigger alert
      echo "999" > "${LAG_FILE}"
    }
  fi
done
