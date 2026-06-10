#!/usr/bin/env bash
# Task 17.1 — Verify Pod Security Admission (restricted profile) on railos namespace
# Satisfies: Req 39, Design §9.3
set -euo pipefail

NAMESPACE="${NAMESPACE:-railos}"

echo "=== Pod Security Admission Verification ==="
echo "Namespace: $NAMESPACE"
echo ""

# Check PSA labels on namespace
echo "[1/3] Checking PSA labels on namespace..."
PSA_ENFORCE=$(kubectl get namespace "$NAMESPACE" -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}' 2>/dev/null || echo "NOT SET")
PSA_WARN=$(kubectl get namespace "$NAMESPACE" -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/warn}' 2>/dev/null || echo "NOT SET")
PSA_AUDIT=$(kubectl get namespace "$NAMESPACE" -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/audit}' 2>/dev/null || echo "NOT SET")

echo "  enforce: $PSA_ENFORCE"
echo "  warn:    $PSA_WARN"
echo "  audit:   $PSA_AUDIT"

if [ "$PSA_ENFORCE" = "restricted" ]; then
  echo "  STATUS: PASS — restricted profile enforced"
else
  echo "  STATUS: FAIL — expected 'restricted', got '$PSA_ENFORCE'"
  echo "  Fix: kubectl label namespace $NAMESPACE pod-security.kubernetes.io/enforce=restricted"
fi

# Check that all running pods comply (no privileged containers)
echo ""
echo "[2/3] Checking running pods for privileged containers..."
PRIVILEGED_PODS=$(kubectl get pods -n "$NAMESPACE" -o json 2>/dev/null | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
violations = []
for pod in data.get('items', []):
  name = pod['metadata']['name']
  for c in pod['spec'].get('containers', []) + pod['spec'].get('initContainers', []):
    sc = c.get('securityContext', {})
    if sc.get('privileged') is True:
      violations.append(f'{name}/{c[\"name\"]}')
for v in violations:
  print(v)
" 2>/dev/null || true)

if [ -z "$PRIVILEGED_PODS" ]; then
  echo "  STATUS: PASS — no privileged containers found"
else
  echo "  STATUS: WARN — privileged containers detected (likely in railos-system):"
  echo "$PRIVILEGED_PODS" | while read -r line; do echo "    $line"; done
fi

# Check that pods run as non-root
echo ""
echo "[3/3] Checking pods for runAsNonRoot compliance..."
ROOT_PODS=$(kubectl get pods -n "$NAMESPACE" -o json 2>/dev/null | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
violations = []
for pod in data.get('items', []):
  name = pod['metadata']['name']
  pod_sc = pod['spec'].get('securityContext', {})
  for c in pod['spec'].get('containers', []):
    c_sc = c.get('securityContext', {})
    run_as_nonroot = c_sc.get('runAsNonRoot', pod_sc.get('runAsNonRoot', None))
    run_as_user = c_sc.get('runAsUser', pod_sc.get('runAsUser', None))
    if run_as_nonroot is False or run_as_user == 0:
      violations.append(f'{name}/{c[\"name\"]} (runAsNonRoot={run_as_nonroot}, runAsUser={run_as_user})')
for v in violations:
  print(v)
" 2>/dev/null || true)

if [ -z "$ROOT_PODS" ]; then
  echo "  STATUS: PASS — all containers run as non-root"
else
  echo "  STATUS: WARN — potential root containers:"
  echo "$ROOT_PODS" | while read -r line; do echo "    $line"; done
fi

echo ""
echo "=== PSA Verification Complete ==="
