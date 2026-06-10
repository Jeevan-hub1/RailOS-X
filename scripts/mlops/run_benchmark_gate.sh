#!/usr/bin/env bash
# Task 18.2 — Run benchmark gate before model deployment
# Satisfies: Req 14 (regression gate), Design §11
set -euo pipefail

MODEL_ID="${1:-}"
CANDIDATE_VERSION="${2:-}"
NAMESPACE="${NAMESPACE:-railos}"

if [ -z "$MODEL_ID" ] || [ -z "$CANDIDATE_VERSION" ]; then
  echo "Usage: $0 <model_id> <candidate_version>"
  echo "Example: $0 defect_detector 1.3.0"
  exit 1
fi

echo "=== RailOS Benchmark Gate ==="
echo "  Model:     $MODEL_ID"
echo "  Candidate: $CANDIDATE_VERSION"
echo ""

# Run the pytest-based benchmark suite
kubectl exec -n "$NAMESPACE" deploy/mlflow -- \
  python3 -m pytest \
    /app/benchmarks/test_${MODEL_ID}_benchmark.py \
    --model-id "$MODEL_ID" \
    --candidate-version "$CANDIDATE_VERSION" \
    --regression-threshold 0.05 \
    -v --tb=short 2>&1 || {
  echo ""
  echo "FAIL — Benchmark gate blocked deployment of $MODEL_ID@$CANDIDATE_VERSION"
  echo "       REGRESSION_DETECTED: check output above for failing metrics"
  # Emit REGRESSION_DETECTED to Kafka
  kubectl exec -n "$NAMESPACE" deploy/mlflow -- \
    python3 -c "
from kafka import KafkaProducer
import json
p = KafkaProducer(bootstrap_servers='railos-kafka-kafka-bootstrap.railos:9092', acks='all')
p.send('monitoring.alerts', json.dumps({
    'alertType': 'REGRESSION_DETECTED',
    'modelId': '$MODEL_ID',
    'candidateVersion': '$CANDIDATE_VERSION',
}).encode())
p.flush()
" 2>/dev/null || true
  exit 1
}

echo ""
echo "PASS — Benchmark gate passed for $MODEL_ID@$CANDIDATE_VERSION"
echo "       Model approved for deployment."
