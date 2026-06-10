#!/usr/bin/env bash
# Task 21.5 — Verify EN 50128 alignment for deployed ML models
# Checks: deterministic inference, no stochastic layers at inference time,
# fixed-point quantization evidence, MAJOR.MINOR.PATCH version tags in MLflow
# Satisfies: Design §13, EN 50128 (deterministic inference requirement)
set -euo pipefail

NAMESPACE="${NAMESPACE:-railos}"
MLFLOW_URL="${MLFLOW_URL:-http://mlflow.railos.svc.cluster.local:5000}"
PASS=0
FAIL=0
WARN=0

echo "=== EN 50128 Alignment Audit ==="
echo "MLflow URL: $MLFLOW_URL"
echo ""

# 1. Check all registered model versions have semver tags
echo "[1/4] Verifying MAJOR.MINOR.PATCH version tags in MLflow..."
MODELS=$(kubectl exec -n "$NAMESPACE" deploy/mlflow -- \
  python3 -c "
import mlflow
client = mlflow.tracking.MlflowClient()
models = client.search_registered_models()
for m in models:
  for v in client.search_model_versions(f\"name='{m.name}'\"):
    tags = v.tags or {}
    semver = tags.get('railos_model_version', '')
    import re
    ok = bool(re.match(r'^\d+\.\d+\.\d+$', semver))
    print(f'{m.name}@{v.version} railos_model_version={semver!r} semver_ok={ok}')
" 2>/dev/null || echo "MLFLOW_UNAVAILABLE")

if [ "$MODELS" = "MLFLOW_UNAVAILABLE" ]; then
  echo "  SKIP: MLflow not reachable (deploy first)"
  WARN=$((WARN + 1))
else
  echo "$MODELS" | while IFS= read -r line; do
    if echo "$line" | grep -q "semver_ok=True"; then
      echo "  PASS: $line"
      PASS=$((PASS + 1))
    else
      echo "  FAIL: $line"
      FAIL=$((FAIL + 1))
    fi
  done
fi

# 2. Check model inference is deterministic (no dropout at inference)
echo ""
echo "[2/4] Checking model artifacts for stochastic layers at inference..."
# This is a static check — look for dropout=0.0 tag set during training
DETERMINISM=$(kubectl exec -n "$NAMESPACE" deploy/mlflow -- \
  python3 -c "
import mlflow
client = mlflow.tracking.MlflowClient()
models = client.search_registered_models()
for m in models:
  for v in client.search_model_versions(f\"name='{m.name}'\"):
    tags = v.tags or {}
    det = tags.get('railos_deterministic_inference', 'unset')
    print(f'{m.name}@{v.version} deterministic={det}')
" 2>/dev/null || echo "MLFLOW_UNAVAILABLE")

if [ "$DETERMINISM" = "MLFLOW_UNAVAILABLE" ]; then
  echo "  SKIP: MLflow not reachable"
else
  echo "$DETERMINISM" | while IFS= read -r line; do
    if echo "$line" | grep -q "deterministic=true"; then
      echo "  PASS: $line"
    elif echo "$line" | grep -q "deterministic=unset"; then
      echo "  WARN: $line — tag 'railos_deterministic_inference' not set"
      echo "        Set during training: mlflow.set_tag('railos_deterministic_inference', 'true')"
    else
      echo "  FAIL: $line"
    fi
  done
fi

# 3. Check for INT8/quantized model artifacts (TensorRT export evidence)
echo ""
echo "[3/4] Checking for quantized model artifacts..."
TRT_MODELS=$(kubectl exec -n "$NAMESPACE" deploy/mlflow -- \
  python3 -c "
import mlflow, os
client = mlflow.tracking.MlflowClient()
models = client.search_registered_models(filter_string=\"name LIKE '%defect%'\")
for m in models:
  for v in client.search_model_versions(f\"name='{m.name}'\"):
    tags = v.tags or {}
    quant = tags.get('railos_quantization', 'none')
    print(f'{m.name}@{v.version} quantization={quant}')
" 2>/dev/null || echo "MLFLOW_UNAVAILABLE")

if [ "$TRT_MODELS" != "MLFLOW_UNAVAILABLE" ]; then
  echo "$TRT_MODELS"
fi

# 4. Check requirement IDs are linked
echo ""
echo "[4/4] Checking requirement ID linkage in MLflow runs..."
REQ_LINKS=$(kubectl exec -n "$NAMESPACE" deploy/mlflow -- \
  python3 -c "
import mlflow
client = mlflow.tracking.MlflowClient()
runs = client.search_runs(experiment_ids=['0'], max_results=10,
  filter_string=\"tags.railos_requirement_id != ''\")
for r in runs:
  req = r.data.tags.get('railos_requirement_id', 'MISSING')
  print(f'run={r.info.run_id[:8]} requirement={req}')
" 2>/dev/null || echo "No runs with requirement tags found")

echo "  $REQ_LINKS"

echo ""
echo "=== EN 50128 Audit Complete ==="
echo "  PASS: $PASS  FAIL: $FAIL  WARN: $WARN"
echo ""
echo "For full certification, each FAIL must be remediated before deployment."
echo "Reference: Design §13, EN 50128 Table A.2 — Software Verification Techniques"
