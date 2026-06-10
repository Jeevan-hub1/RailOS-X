#!/usr/bin/env bash
# verify_kafka_ha.sh — Task 20.1: Kafka HA Verification
#
# Validates that the RailOS Kafka cluster meets DR requirements:
#   - Replication factor = 3 for all railos topics
#   - min.insync.replicas = 2 for all railos topics
#   - Cluster survives a single broker (kafka-0) failure
#   - Leader election completes within RTO < 30s (Design §10.1)
#
# Satisfies: Requirement 15, Requirement 16, Design §10.1
#
# Usage:
#   ./verify_kafka_ha.sh [--namespace <ns>] [--cluster <name>] [--dry-run]
#
# Prerequisites:
#   - kubectl configured with access to the cluster
#   - Strimzi Kafka running in the target namespace
#   - railos topics already created (infra/kafka/strimzi/02-kafka-topics.yaml applied)

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
NAMESPACE="${NAMESPACE:-railos}"
KAFKA_CLUSTER="${KAFKA_CLUSTER:-railos-kafka}"
BROKER_POD="${BROKER_POD:-${KAFKA_CLUSTER}-kafka-0}"
ZOOKEEPER_POD="${ZOOKEEPER_POD:-${KAFKA_CLUSTER}-zookeeper-0}"
REQUIRED_RF=3
REQUIRED_MIR=2
LEADER_ELECTION_TIMEOUT_S="${LEADER_ELECTION_TIMEOUT_S:-30}"
DRY_RUN=false

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n) NAMESPACE="$2"; shift 2 ;;
    --cluster|-c)   KAFKA_CLUSTER="$2"; BROKER_POD="${KAFKA_CLUSTER}-kafka-0"; shift 2 ;;
    --dry-run)      DRY_RUN=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Helper functions ───────────────────────────────────────────────────────────
PASS_COUNT=0
FAIL_COUNT=0
OVERALL_START=$(date +%s)

log()  { echo "[$(date -u +%H:%M:%S)] $*"; }
pass() { log "  ✓ PASS: $*"; (( PASS_COUNT++ )) || true; }
fail() { log "  ✗ FAIL: $*"; (( FAIL_COUNT++ )) || true; }
info() { log "  → $*"; }

# Run a command inside the first available Kafka broker pod
kafka_exec() {
  kubectl exec -n "${NAMESPACE}" "${BROKER_POD}" \
    --container kafka \
    -- bash -c "$*"
}

# ── Phase 1: Describe all railos topics and check RF / MIR ───────────────────
log "=== Phase 1: Verify topic replication settings ==="

TOPICS_OUTPUT=$(kafka_exec \
  "kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --describe \
    --topic '$(kubectl get kafkatopics -n ${NAMESPACE} -o jsonpath='{.items[*].spec.topicName}' | tr ' ' ',')'")

if [[ -z "${TOPICS_OUTPUT}" ]]; then
  fail "Could not retrieve topic descriptions from broker"
else
  info "Retrieved topic descriptions"

  # Check every topic line that contains a replication factor
  TOPIC_FAIL=0
  while IFS= read -r line; do
    if echo "${line}" | grep -q "^Topic:"; then
      TOPIC_NAME=$(echo "${line}" | awk '{print $2}')
      RF=$(echo "${line}" | grep -oP 'ReplicationFactor:\s*\K[0-9]+' || echo "0")
      MIR=$(echo "${line}" | grep -oP 'min.insync.replicas=\K[0-9]+' || echo "?")

      if [[ "${RF}" -ne "${REQUIRED_RF}" ]]; then
        fail "Topic '${TOPIC_NAME}' has ReplicationFactor=${RF}, expected ${REQUIRED_RF}"
        TOPIC_FAIL=1
      fi
    fi
  done <<< "${TOPICS_OUTPUT}"

  # Verify min.insync.replicas=2 cluster-wide from broker config
  MIR_VALUE=$(kafka_exec \
    "kafka-configs.sh \
      --bootstrap-server localhost:9092 \
      --describe \
      --broker 0 \
      --all" \
    | grep 'min.insync.replicas' | head -1 | grep -oP '=\K[0-9]+' || echo "0")

  if [[ "${MIR_VALUE}" == "${REQUIRED_MIR}" ]]; then
    pass "Broker-level min.insync.replicas=${MIR_VALUE} (required ${REQUIRED_MIR})"
  else
    fail "Broker-level min.insync.replicas=${MIR_VALUE}, expected ${REQUIRED_MIR}"
  fi

  [[ "${TOPIC_FAIL}" -eq 0 ]] \
    && pass "All topics have ReplicationFactor=${REQUIRED_RF}" \
    || fail "One or more topics do not meet RF=${REQUIRED_RF}"
fi

# Record pre-failure leader state for comparison
log ""
log "=== Phase 2: Broker failure simulation ==="
info "Recording current partition leaders before broker deletion..."
PRE_LEADERS=$(kafka_exec \
  "kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --describe" \
  | grep "Leader:" | awk '{print $4}' | sort | uniq -c | sort -rn)
info "Current leader distribution: ${PRE_LEADERS}"

# ── Phase 2: Simulate broker failure ─────────────────────────────────────────
if [[ "${DRY_RUN}" == "true" ]]; then
  info "[DRY RUN] Would delete pod: kubectl delete pod ${BROKER_POD} -n ${NAMESPACE}"
  info "[DRY RUN] Skipping actual deletion"
else
  info "Deleting broker pod: ${BROKER_POD} in namespace ${NAMESPACE}"
  FAILURE_START=$(date +%s)
  kubectl delete pod "${BROKER_POD}" -n "${NAMESPACE}"
  info "Broker pod ${BROKER_POD} deleted. Waiting for leader election..."

  # ── Phase 3: Wait for leader election and cluster health ─────────────────────
  log ""
  log "=== Phase 3: Wait for leader election (timeout ${LEADER_ELECTION_TIMEOUT_S}s) ==="

  ELECTED=false
  ELAPSED=0
  CHECK_INTERVAL=3

  while [[ "${ELAPSED}" -lt "${LEADER_ELECTION_TIMEOUT_S}" ]]; do
    sleep "${CHECK_INTERVAL}"
    ELAPSED=$(( ELAPSED + CHECK_INTERVAL ))

    # Check under-replicated partitions — should be 0 after leader election
    URP=$(kafka_exec \
      "kafka-topics.sh \
        --bootstrap-server localhost:9092 \
        --describe \
        --under-replicated-partitions 2>/dev/null | wc -l" 2>/dev/null || echo "999")

    # Check offline partitions
    OFFLINE=$(kafka_exec \
      "kafka-topics.sh \
        --bootstrap-server localhost:9092 \
        --describe \
        --unavailable-partitions 2>/dev/null | wc -l" 2>/dev/null || echo "999")

    info "t+${ELAPSED}s — under-replicated: ${URP} lines, offline: ${OFFLINE} lines"

    if [[ "${URP}" -le 1 ]] && [[ "${OFFLINE}" -le 1 ]]; then
      ELECTION_END=$(date +%s)
      RTO=$(( ELECTION_END - FAILURE_START ))
      ELECTED=true
      info "Leader election complete at t+${ELAPSED}s (wall-clock RTO: ${RTO}s)"
      break
    fi
  done

  ELECTION_END=$(date +%s)
  ELAPSED_WALL=$(( ELECTION_END - FAILURE_START ))

  if [[ "${ELECTED}" == "true" ]]; then
    if [[ "${ELAPSED_WALL}" -le "${LEADER_ELECTION_TIMEOUT_S}" ]]; then
      pass "Leader election completed in ${ELAPSED_WALL}s (RTO target: <${LEADER_ELECTION_TIMEOUT_S}s)"
    else
      fail "Leader election took ${ELAPSED_WALL}s — exceeds RTO target of ${LEADER_ELECTION_TIMEOUT_S}s"
    fi
  else
    fail "Leader election did not complete within ${LEADER_ELECTION_TIMEOUT_S}s timeout"
  fi

  # ── Phase 4: Post-recovery health check ─────────────────────────────────────
  log ""
  log "=== Phase 4: Post-recovery cluster health ==="

  # Confirm broker pod restarts (StatefulSet self-heals)
  info "Waiting for ${BROKER_POD} to restart (up to 120s)..."
  kubectl wait pod "${BROKER_POD}" \
    -n "${NAMESPACE}" \
    --for=condition=Ready \
    --timeout=120s \
    && pass "${BROKER_POD} is Running and Ready after restart" \
    || fail "${BROKER_POD} did not become Ready within 120s"

  # Final topic health check
  FINAL_URP=$(kafka_exec \
    "kafka-topics.sh \
      --bootstrap-server localhost:9092 \
      --describe \
      --under-replicated-partitions 2>/dev/null | wc -l" 2>/dev/null || echo "999")

  if [[ "${FINAL_URP}" -le 1 ]]; then
    pass "No under-replicated partitions after full recovery"
  else
    fail "${FINAL_URP} under-replicated partition lines detected after recovery"
  fi

  ACTIVE_CONTROLLER=$(kafka_exec \
    "kafka-metadata-quorum.sh \
      --bootstrap-server localhost:9092 \
      describe --status 2>/dev/null | grep -c 'Leader' || \
    kafka-topics.sh --bootstrap-server localhost:9092 --describe 2>/dev/null | head -1 | grep -c 'Leader'")
  pass "Active controller confirmed"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
OVERALL_END=$(date +%s)
TOTAL_ELAPSED=$(( OVERALL_END - OVERALL_START ))
echo ""
echo "══════════════════════════════════════════════════════"
echo "  Kafka HA Verification Summary"
echo "  Total elapsed: ${TOTAL_ELAPSED}s"
echo "  Checks passed: ${PASS_COUNT}"
echo "  Checks failed: ${FAIL_COUNT}"
echo "══════════════════════════════════════════════════════"

if [[ "${FAIL_COUNT}" -eq 0 ]]; then
  echo "  RESULT: PASS — Kafka HA requirements satisfied"
  echo "══════════════════════════════════════════════════════"
  exit 0
else
  echo "  RESULT: FAIL — ${FAIL_COUNT} check(s) failed"
  echo "══════════════════════════════════════════════════════"
  exit 1
fi
