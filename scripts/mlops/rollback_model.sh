#!/usr/bin/env bash
# Task 18.7 — Model rollback via API (RTO ≤ 15 min, no Edge_Node restart)
# Satisfies: Req 11 C3, Design §11
set -euo pipefail

MODEL_ID="${1:-}"
API_BASE="${API_BASE:-http://localhost:8000}"
TOKEN="${RAILOS_TOKEN:-}"
MAX_WAIT_S=900  # 15 minutes

if [ -z "$MODEL_ID" ]; then
  echo "Usage: $0 <model_id>"
  echo "Example: $0 defect_detector"
  exit 1
fi

AUTH_HEADER=""
[ -n "$TOKEN" ] && AUTH_HEADER="-H 'Authorization: Bearer $TOKEN'"

echo "=== Model Rollback ==="
echo "  Model: $MODEL_ID"
echo "  API:   $API_BASE"
echo ""

START_TIME=$(date +%s)

# Call rollback API
echo "[1/3] Requesting rollback..."
RESPONSE=$(curl -s -w "\n%{http_code}" \
  -X POST \
  -H "Content-Type: application/json" \
  ${TOKEN:+-H "Authorization: Bearer $TOKEN"} \
  "$API_BASE/api/v1/models/$MODEL_ID/rollback")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)

echo "  HTTP: $HTTP_CODE"
echo "  Response: $BODY"

case "$HTTP_CODE" in
  200|202)
    echo "  Rollback initiated."
    ;;
  404)
    echo "FAIL — NO_PREVIOUS_VERSION: no prior version exists for $MODEL_ID"
    exit 1
    ;;
  401)
    echo "FAIL — HTTP 401: set RAILOS_TOKEN to an Engineering_Team JWT"
    exit 1
    ;;
  *)
    echo "FAIL — unexpected HTTP $HTTP_CODE"
    exit 1
    ;;
esac

# Poll for completion
echo ""
echo "[2/3] Waiting for rollback to complete (max ${MAX_WAIT_S}s)..."
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT_S ]; do
  STATUS=$(curl -s \
    ${TOKEN:+-H "Authorization: Bearer $TOKEN"} \
    "$API_BASE/api/v1/models/$MODEL_ID/status" 2>/dev/null | \
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('rollback_status','unknown'))" 2>/dev/null || echo "unknown")

  if [ "$STATUS" = "complete" ]; then
    ELAPSED=$(($(date +%s) - START_TIME))
    echo ""
    echo "[3/3] PASS — Rollback completed in ${ELAPSED}s (≤ ${MAX_WAIT_S}s)"
    exit 0
  elif [ "$STATUS" = "failed" ]; then
    echo ""
    echo "FAIL — Rollback failed. Check $API_BASE/api/v1/models/$MODEL_ID/status"
    exit 1
  fi

  sleep 5
  ELAPSED=$(($(date +%s) - START_TIME))
  printf "."
done

echo ""
echo "FAIL — ROLLBACK_TIMEOUT: rollback did not complete in ${MAX_WAIT_S}s"
echo "       ROLLBACK_TIMEOUT alert should have been emitted to monitoring.alerts"
exit 1
