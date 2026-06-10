#!/usr/bin/env bash
# Task 20.2 — Verify InfluxDB WAL replication ≤60s RPO
# Satisfies: Req 16 C2 (RPO ≤ 60s), Design §10.1
set -euo pipefail

NAMESPACE="${NAMESPACE:-railos}"
PRIMARY_POD="influxdb-primary-0"
STANDBY_POD="influxdb-standby-0"
MAX_WAIT_S=60
TEST_MEASUREMENT="dr_test_$(date +%s)"
INFLUX_TOKEN="${INFLUX_TOKEN:-railos-admin-token}"
INFLUX_ORG="${INFLUX_ORG:-railos}"
INFLUX_BUCKET="${INFLUX_BUCKET:-sensor-events}"

echo "=== InfluxDB WAL Replication Test ==="
echo "Measurement: $TEST_MEASUREMENT"
echo ""

# Write a test measurement to the primary
echo "[1/3] Writing test measurement to primary..."
kubectl exec -n "$NAMESPACE" "$PRIMARY_POD" -- \
  influx write \
    --token "$INFLUX_TOKEN" \
    --org "$INFLUX_ORG" \
    --bucket "$INFLUX_BUCKET" \
    "${TEST_MEASUREMENT},source=dr-test value=1.0 $(date +%s)000000000"

WRITE_TIME=$(date +%s)
echo "    Written at $(date -u -d @$WRITE_TIME '+%Y-%m-%dT%H:%M:%SZ')"

# Poll standby for the measurement
echo "[2/3] Polling standby for replication (max ${MAX_WAIT_S}s)..."
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT_S ]; do
  COUNT=$(kubectl exec -n "$NAMESPACE" "$STANDBY_POD" -- \
    influx query \
      --token "$INFLUX_TOKEN" \
      --org "$INFLUX_ORG" \
      "from(bucket:\"$INFLUX_BUCKET\") |> range(start:-2m) |> filter(fn:(r) => r._measurement == \"$TEST_MEASUREMENT\") |> count()" \
      --raw 2>/dev/null | grep -c ",1$" || true)
  if [ "${COUNT:-0}" -gt 0 ]; then
    echo ""
    echo "[3/3] PASS — Replication lag: ${ELAPSED}s (≤ ${MAX_WAIT_S}s RPO threshold)"
    exit 0
  fi
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  printf "."
done

echo ""
echo "[3/3] FAIL — Measurement not found on standby after ${MAX_WAIT_S}s"
echo "     Check: kubectl logs -n $NAMESPACE $STANDBY_POD"
exit 1
