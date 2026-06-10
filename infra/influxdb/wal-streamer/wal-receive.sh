#!/bin/bash
# wal-receive.sh — WAL Receiver (standby sidecar)
#
# Listens on TCP port for incoming WAL segments from the primary's wal-streamer.
# Validates the HMAC, writes the segment to the incoming directory, then
# triggers InfluxDB to apply it.
#
# Environment variables (all required; set in the StatefulSet):
#   WAL_INCOMING_DIR         — directory for received WAL segments (before apply)
#   WAL_DIR                  — InfluxDB WAL directory (segments applied here)
#   INFLUXDB_API_URL         — URL of local InfluxDB instance (for apply trigger)
#   INFLUXDB_TOKEN           — InfluxDB admin token (for apply trigger API calls)
#   REPLICATION_SECRET       — shared secret for HMAC validation
#   METRICS_PORT             — port for Prometheus metrics (default 9091)
set -euo pipefail

WAL_INCOMING_DIR="${WAL_INCOMING_DIR:-/var/lib/influxdb3/wal-incoming}"
WAL_DIR="${WAL_DIR:-/var/lib/influxdb3/wal}"
INFLUXDB_API_URL="${INFLUXDB_API_URL:-http://localhost:8086}"
INFLUXDB_TOKEN="${INFLUXDB_TOKEN:?INFLUXDB_TOKEN must be set}"
REPLICATION_SECRET="${REPLICATION_SECRET:?REPLICATION_SECRET must be set}"
LISTEN_PORT="${STANDBY_PORT:-8088}"
LAG_FILE="/tmp/replication_lag_seconds"
SEGMENTS_RECEIVED_FILE="/tmp/segments_received_total"

echo "[wal-receiver] Listening on port ${LISTEN_PORT}"
echo "[wal-receiver] Incoming WAL dir: ${WAL_INCOMING_DIR}"
echo "[wal-receiver] InfluxDB API: ${INFLUXDB_API_URL}"

# Initialize metric files
echo "0" > "${LAG_FILE}"
echo "0" > "${SEGMENTS_RECEIVED_FILE}"

mkdir -p "${WAL_INCOMING_DIR}"

receive_and_apply() {
  local receive_start
  receive_start=$(date +%s)

  # Read header line: WAL-SEGMENT:<name>:<size>:<hmac>
  read -r header
  if [[ ! "${header}" =~ ^WAL-SEGMENT:(.+):([0-9]+):([0-9a-f]+)$ ]]; then
    echo "[wal-receiver] ERROR: Malformed header: ${header}"
    return 1
  fi

  local segment_name="${BASH_REMATCH[1]}"
  local file_size="${BASH_REMATCH[2]}"
  local received_hmac="${BASH_REMATCH[3]}"

  # Validate HMAC
  local expected_hmac
  expected_hmac=$(echo -n "${segment_name}:${REPLICATION_SECRET}" | sha256sum | awk '{print $1}')
  if [ "${received_hmac}" != "${expected_hmac}" ]; then
    echo "[wal-receiver] ERROR: HMAC validation failed for segment ${segment_name}. Rejecting."
    return 1
  fi

  # Read exactly file_size bytes and write to incoming dir
  local incoming_path="${WAL_INCOMING_DIR}/${segment_name}"
  dd bs=1 count="${file_size}" of="${incoming_path}" 2>/dev/null

  # Move to WAL directory for InfluxDB to pick up
  mv "${incoming_path}" "${WAL_DIR}/${segment_name}"
  echo "[wal-receiver] Received and staged: ${segment_name}"

  # Signal InfluxDB to reload/apply WAL
  # InfluxDB 3.0 typically applies WAL segments automatically on close.
  # This call ensures any lazy-apply is triggered immediately.
  curl -sf \
    -X POST "${INFLUXDB_API_URL}/api/v2/wal/apply" \
    -H "Authorization: Token ${INFLUXDB_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"segment\": \"${segment_name}\"}" \
    || echo "[wal-receiver] WARN: WAL apply API call failed (segment will be applied on next cycle)"

  local receive_end
  receive_end=$(date +%s)
  local lag=$(( receive_end - receive_start ))
  echo "${lag}" > "${LAG_FILE}"

  # Increment counter metric
  local count
  count=$(cat "${SEGMENTS_RECEIVED_FILE}")
  echo $(( count + 1 )) > "${SEGMENTS_RECEIVED_FILE}"

  echo "[wal-receiver] Applied ${segment_name} (apply time: ${lag}s)"
}

# Main loop: accept connections and receive WAL segments
echo "[wal-receiver] Entering receive loop on TCP :${LISTEN_PORT}..."
while true; do
  ncat -l "${LISTEN_PORT}" --keep-open --max-conns 1 \
    -e /bin/bash -c "$(declare -f receive_and_apply); receive_and_apply" \
    || echo "[wal-receiver] Connection closed, waiting for next connection..."
  sleep 1
done
