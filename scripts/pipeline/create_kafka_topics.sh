#!/usr/bin/env bash
# Task 4.1 — Create all RailOS Kafka topics (Design §4.1)
# Satisfies: Req 1 (sensor data pipeline), Req 9 (security anomalies)
# Run once after Kafka cluster is healthy.
set -euo pipefail

NAMESPACE="${NAMESPACE:-railos}"
BOOTSTRAP="${BOOTSTRAP:-railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092}"
KAFKA_POD=$(kubectl get pod -n "$NAMESPACE" -l "strimzi.io/kind=Kafka" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "kafka-0")

# Shorthand to create a topic idempotently
create_topic() {
  local TOPIC="$1" PARTITIONS="$2" REPLICAS="$3" RETENTION_MS="${4:--1}"
  echo "  Creating: $TOPIC (p=$PARTITIONS rf=$REPLICAS ttl=${RETENTION_MS}ms)"
  kubectl exec -n "$NAMESPACE" "$KAFKA_POD" -- \
    bin/kafka-topics.sh \
      --bootstrap-server "$BOOTSTRAP" \
      --create --if-not-exists \
      --topic "$TOPIC" \
      --partitions "$PARTITIONS" \
      --replication-factor "$REPLICAS" \
      --config "min.insync.replicas=2" \
      --config "retention.ms=$RETENTION_MS" \
      --config "compression.type=lz4" \
    2>&1 | grep -v "already exists" || true
}

echo "=== Creating RailOS Kafka Topics ==="
echo "Bootstrap: $BOOTSTRAP"
echo ""

echo "--- Sensor topics (7-day retention, high partition count)"
create_topic "track.sensor.vibration"   12 3 604800000
create_topic "track.sensor.temperature"  6 3 604800000
create_topic "track.sensor.acoustic"     6 3 604800000

echo "--- Train telemetry topics"
create_topic "train.telemetry.position" 12 3 604800000
create_topic "train.telemetry.omrs"      8 3 604800000
create_topic "train.telemetry.wild"      8 3 604800000

echo "--- Vision / defect topics"
create_topic "vision.defect.alerts"     6 3 2592000000   # 30 days
create_topic "vision.defect.gradcam"    3 3 604800000

echo "--- Signaling"
create_topic "signaling.state"          6 3 604800000

echo "--- Advisory topics (30-day retention)"
create_topic "maintenance.advisories"   3 3 2592000000
create_topic "scheduling.proposals"     3 3 2592000000

echo "--- Security (365-day retention)"
create_topic "security.anomalies"       3 3 31536000000

echo "--- Monitoring"
create_topic "monitoring.alerts"        6 3 604800000

echo "--- Dead-letter queues (30 days for debugging)"
create_topic "dead-letter.schema-failures"  3 3 2592000000
create_topic "dead-letter.adapter-failures" 3 3 2592000000

echo "--- Audit topics (365-day retention)"
create_topic "audit.inference"      3 3 31536000000
create_topic "audit.authorization"  3 3 31536000000

echo ""
echo "=== Topic creation complete. Listing all topics ==="
kubectl exec -n "$NAMESPACE" "$KAFKA_POD" -- \
  bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --list | grep -v "^__"
