#!/usr/bin/env bash
# Task 21.2 — Generate traceability report for a given subsystem version
# Calls the traceability report API and saves JSON/PDF output
# Satisfies: Req 35 C3, Design §13.1
set -euo pipefail

SUBSYSTEM_VERSION="${1:-}"
API_BASE="${API_BASE:-http://localhost:8000}"
TOKEN="${RAILOS_TOKEN:-}"
OUTPUT_DIR="${OUTPUT_DIR:-./reports}"

if [ -z "$SUBSYSTEM_VERSION" ]; then
  echo "Usage: $0 <subsystem-version> [api-base-url]"
  echo "Example: $0 defect_detector@1.2.3"
  exit 1
fi

[ -n "$2" ] && API_BASE="$2"

echo "=== Traceability Report ==="
echo "  Subsystem: $SUBSYSTEM_VERSION"
echo "  API:       $API_BASE"
echo ""

mkdir -p "$OUTPUT_DIR"
OUTPUT_FILE="$OUTPUT_DIR/traceability-${SUBSYSTEM_VERSION//[@\/]/-}-$(date +%Y%m%d).json"

if [ -n "$TOKEN" ]; then
  AUTH_HEADER="Authorization: Bearer $TOKEN"
else
  echo "  WARN: RAILOS_TOKEN not set — request may be rejected (HTTP 401)"
  AUTH_HEADER="X-No-Auth: true"
fi

echo "Fetching report..."
HTTP_CODE=$(curl -s -o "$OUTPUT_FILE" -w "%{http_code}" \
  -H "$AUTH_HEADER" \
  -H "Accept: application/json" \
  "$API_BASE/api/v1/traceability/$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$SUBSYSTEM_VERSION")")

if [ "$HTTP_CODE" = "200" ]; then
  echo "  PASS: Report saved to $OUTPUT_FILE"
  echo ""
  echo "Summary:"
  python3 -c "
import json, sys
with open('$OUTPUT_FILE') as f:
  d = json.load(f)
reqs = d.get('requirements', [])
hazards = d.get('hazards', [])
evidence = d.get('evidenceRecords', [])
print(f'  Requirements linked: {len(reqs)}')
print(f'  Hazards covered:     {len(hazards)}')
print(f'  Evidence records:    {len(evidence)}')
if reqs:
  print(f'  Req IDs: {[r.get(\"requirementId\") for r in reqs[:5]]}...')
" 2>/dev/null || cat "$OUTPUT_FILE" | head -30
else
  echo "  FAIL: API returned HTTP $HTTP_CODE"
  cat "$OUTPUT_FILE"
  exit 1
fi
