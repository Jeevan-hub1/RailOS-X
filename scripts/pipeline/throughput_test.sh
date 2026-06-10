#!/usr/bin/env bash
# Task 4.8 — Verify sustained 10,000 events/s ingestion throughput
# Satisfies: Req 1 C6 (≥10,000 events/sec), Design §4.1
set -euo pipefail

NAMESPACE="${NAMESPACE:-railos}"
BOOTSTRAP="${BOOTSTRAP:-railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092}"
KAFKA_POD=$(kubectl get pod -n "$NAMESPACE" -l "strimzi.io/kind=Kafka" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "kafka-0")
TARGET_EPS=10000       # events per second
TEST_DURATION_S=60     # run for 60 seconds
TOPIC="track.sensor.vibration"
NUM_RECORDS=$((TARGET_EPS * TEST_DURATION_S))

echo "=== Kafka Throughput Test ==="
echo "Target: ${TARGET_EPS} events/sec for ${TEST_DURATION_S}s"
echo "Total records: ${NUM_RECORDS}"
echo "Topic: $TOPIC"
echo ""

# Use Kafka's built-in producer perf test
echo "[1/2] Running producer performance test..."
START_TIME=$(date +%s)

kubectl exec -n "$NAMESPACE" "$KAFKA_POD" -- \
  bin/kafka-producer-perf-test.sh \
    --topic "$TOPIC" \
    --num-records "$NUM_RECORDS" \
    --record-size 512 \
    --throughput "$TARGET_EPS" \
    --producer-props bootstrap.servers="$BOOTSTRAP" \
      acks=all \
      batch.size=65536 \
      linger.ms=5 \
      compression.type=lz4 | tail -5

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "[2/2] Results:"
echo "  Duration: ${ELAPSED}s"
echo "  Records:  ${NUM_RECORDS}"
echo "  Est. throughput: $((NUM_RECORDS / ELAPSED)) events/sec"

if [ $((NUM_RECORDS / ELAPSED)) -ge $TARGET_EPS ]; then
  echo ""
  echo "PASS — Throughput ≥ ${TARGET_EPS} events/sec"
  exit 0
else
  echo ""
  echo "WARN — Throughput may be below ${TARGET_EPS} events/sec target"
  echo "       Check Kafka broker CPU, network, and disk I/O"
  exit 1
fi
