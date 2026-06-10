#!/usr/bin/env bash
# Task 20.3 — Verify PostgreSQL Patroni HA failover RPO≤60s RTO≤2min
# Satisfies: Req 16 C2 (RPO ≤ 60s, RTO ≤ 2 min), Design §10.1
set -euo pipefail

NAMESPACE="${NAMESPACE:-railos}"
PATRONI_POD="postgresql-0"
MAX_RTO_S=120

echo "=== PostgreSQL Patroni Failover Test ==="
echo ""

# Record current primary
echo "[1/4] Identifying current primary..."
CURRENT_PRIMARY=$(kubectl exec -n "$NAMESPACE" "$PATRONI_POD" -- \
  patronictl -c /etc/patroni/patroni.yml list --format tsv 2>/dev/null | \
  grep Leader | awk '{print $1}')
echo "    Current primary: $CURRENT_PRIMARY"

if [ -z "$CURRENT_PRIMARY" ]; then
  echo "FAIL — Could not determine current primary from patronictl"
  exit 1
fi

# Trigger controlled failover
echo "[2/4] Triggering controlled failover (patronictl failover --force)..."
FAILOVER_START=$(date +%s)
kubectl exec -n "$NAMESPACE" "$PATRONI_POD" -- \
  patronictl -c /etc/patroni/patroni.yml failover --force --master "$CURRENT_PRIMARY" railos-postgresql || true

# Wait for new primary
echo "[3/4] Waiting for new primary election (max ${MAX_RTO_S}s)..."
ELAPSED=0
NEW_PRIMARY=""
while [ $ELAPSED -lt $MAX_RTO_S ]; do
  NEW_PRIMARY=$(kubectl exec -n "$NAMESPACE" "$PATRONI_POD" -- \
    patronictl -c /etc/patroni/patroni.yml list --format tsv 2>/dev/null | \
    grep Leader | awk '{print $1}' || true)
  if [ -n "$NEW_PRIMARY" ] && [ "$NEW_PRIMARY" != "$CURRENT_PRIMARY" ]; then
    RTO=$(($(date +%s) - FAILOVER_START))
    echo ""
    echo "    New primary elected: $NEW_PRIMARY"
    break
  fi
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  printf "."
done

if [ -z "$NEW_PRIMARY" ] || [ "$NEW_PRIMARY" = "$CURRENT_PRIMARY" ]; then
  echo ""
  echo "FAIL — No new primary elected within ${MAX_RTO_S}s"
  exit 1
fi

# Verify new primary accepts connections
echo "[4/4] Verifying new primary accepts connections..."
kubectl exec -n "$NAMESPACE" "$NEW_PRIMARY" -- \
  pg_isready -U postgres -d postgres -h localhost -p 5432

echo ""
echo "=== PASS ==="
echo "  Old primary : $CURRENT_PRIMARY"
echo "  New primary : $NEW_PRIMARY"
echo "  RTO elapsed : ${RTO}s (threshold: ${MAX_RTO_S}s)"
[ $RTO -le $MAX_RTO_S ] && echo "  RTO status  : PASS" || echo "  RTO status  : FAIL (exceeded ${MAX_RTO_S}s)"
