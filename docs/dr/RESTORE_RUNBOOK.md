# RailOS Full-System Restore Runbook

**Target RTO:** ≤ 30 minutes from catastrophic failure  
**Satisfies:** Req 16 C1, Design §10.2

---

## Pre-Conditions

Before starting, confirm:
- [ ] Backup bucket `railos-backups` is accessible from the recovery cluster
- [ ] Vault unseal key is available offline (hardware token or secure vault)
- [ ] MinIO credentials for backup bucket are accessible
- [ ] `kubectl` access to the recovery cluster is configured
- [ ] `CLUSTER_ID` is known (e.g. `scr-pilot-01`)

---

## Phase 1: Assess Failure Scope (0–5 min)

```bash
# 1. Check which pods are failing
kubectl get pods -n railos --sort-by=.status.phase

# 2. Check node health
kubectl get nodes

# 3. Check PVC availability
kubectl get pvc -n railos

# 4. Identify failed components
kubectl get events -n railos --sort-by=.lastTimestamp | tail -20
```

**Decision matrix:**

| Scenario | Action |
|----------|--------|
| Kafka only | Restart Kafka StatefulSet → leader auto-elected |
| InfluxDB primary only | Promote standby (see §10.1) |
| PostgreSQL primary only | Patroni auto-failover (verify with `patronictl list`) |
| All storage lost | Full restore from backup (Phase 2–4) |
| Vault sealed | Unseal Vault immediately (critical dependency) |

---

## Phase 2: Restore Core Storage (5–15 min)

### 2A. Unseal Vault (if sealed — do this first)

```bash
VAULT_POD=$(kubectl get pod -n railos -l app=vault -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n railos $VAULT_POD -- vault operator unseal <UNSEAL_KEY>
# Verify
kubectl exec -n railos $VAULT_POD -- vault status | grep -E "Sealed|Version"
```

### 2B. Restore Kafka

```bash
# Kafka uses RF=3 — restart StatefulSet, leader election is automatic
kubectl rollout restart statefulset/kafka -n railos 2>/dev/null || \
  kubectl rollout restart statefulset/railos-kafka-kafka-brokers -n railos

# Wait for all brokers
kubectl rollout status statefulset -n railos -l strimzi.io/kind=Kafka --timeout=120s

# Verify topic health
kubectl exec -n railos $(kubectl get pod -n railos -l strimzi.io/name=railos-kafka -o jsonpath='{.items[0].metadata.name}') -- \
  bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe | grep -E "UnderReplicated|OfflinePartitions"
```

### 2C. Restore InfluxDB

```bash
# If standby is intact — promote it
kubectl exec -n railos influxdb-standby-0 -- influx server-config set is-leader=true

# If both primary and standby lost — restore from backup
BACKUP_DATE=$(date -d "yesterday" +%Y%m%d)
kubectl exec -n railos influxdb-primary-0 -- \
  influx restore --bucket sensor-events /var/backup/${BACKUP_DATE}
```

### 2D. Restore PostgreSQL

```bash
# Patroni should auto-fail over to a healthy replica
kubectl exec -n railos postgresql-0 -- patronictl -c /etc/patroni/patroni.yml list

# If no healthy replica, restore from MinIO backup:
LATEST_BACKUP=$(kubectl exec -n railos backup-job-pod -- \
  /tmp/mc ls --recursive railos/railos-backups/scr-pilot-01/ | grep base.tar.gz | sort | tail -1 | awk '{print $NF}')

kubectl exec -n railos postgresql-0 -- sh -c "
  /tmp/mc cp railos/$LATEST_BACKUP /tmp/base.tar.gz
  rm -rf /var/lib/postgresql/data/pgdata
  tar -xzf /tmp/base.tar.gz -C /var/lib/postgresql/data/pgdata/
  pg_ctl -D /var/lib/postgresql/data/pgdata start
"
```

---

## Phase 3: Restore Application Services (15–25 min)

```bash
# Restart all application deployments in dependency order

# 1. Keycloak (depends on PostgreSQL)
kubectl rollout restart statefulset/keycloak -n railos
kubectl rollout status statefulset/keycloak -n railos --timeout=180s

# 2. Kong (depends on Keycloak JWKS)
kubectl rollout restart deployment/kong -n railos
kubectl rollout status deployment/kong -n railos --timeout=60s

# 3. MLflow (depends on PostgreSQL + MinIO)
kubectl rollout restart deployment/mlflow -n railos

# 4. All AI service deployments
for deploy in defect-detector maintenance-engine delay-predictor marl-scheduler; do
  kubectl rollout restart deployment/$deploy -n railos 2>/dev/null || true
done

# 5. Digital Twin
kubectl rollout restart deployment/digital-twin -n railos 2>/dev/null || true

# 6. Observability stack
kubectl rollout restart deployment/prometheus grafana alertmanager -n railos 2>/dev/null || true
kubectl rollout restart deployment/otel-collector jaeger -n railos 2>/dev/null || true
```

---

## Phase 4: Verify End-to-End Pipeline (25–30 min)

```bash
# 1. Check all pods are Running
kubectl get pods -n railos | grep -v Running | grep -v Completed

# 2. Verify Kafka consumer groups are catching up
kubectl exec -n railos $(kubectl get pod -n railos -l strimzi.io/name=railos-kafka -o jsonpath='{.items[0].metadata.name}') -- \
  bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --all-groups --describe | grep -E "LAG|CONSUMER"

# 3. Verify Keycloak JWT endpoint
curl -s http://$(kubectl get svc keycloak -n railos -o jsonpath='{.spec.clusterIP}'):8080/realms/railos/.well-known/openid-configuration | grep issuer

# 4. Verify authorization gate status
curl -s http://$(kubectl get svc latency-monitor -n railos -o jsonpath='{.spec.clusterIP}'):8080/metrics | grep authorization_gate_status

# 5. Send a test alert through the pipeline and verify e2e latency
# (use the latency monitor /spans endpoint with a synthetic trace)

# 6. Verify Edge_Nodes have reconnected
kubectl logs -n railos -l app=clock-monitor --tail=20 | grep -i "connected\|upload\|reconnect"
```

---

## Post-Restore Checklist

- [ ] All pods Running/Ready (`kubectl get pods -n railos`)
- [ ] Kafka: 0 under-replicated partitions
- [ ] Vault: unsealed and serving secrets
- [ ] Keycloak: JWKS endpoint responding
- [ ] Kong: `/api/v1/` health check passing
- [ ] PostgreSQL: Patroni shows one Leader
- [ ] InfluxDB: replication lag ≤ 60s (run `scripts/dr/verify_influxdb_replication.sh`)
- [ ] E2E latency: p95 ≤ 5s (check Grafana dashboard)
- [ ] Edge_Nodes: reconnected and uploading buffered events
- [ ] Authorization gate: status = operational

---

## Total Target Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 1: Assess | 0–5 min | 5 min |
| Phase 2: Storage | 5–15 min | 15 min |
| Phase 3: Services | 15–25 min | 25 min |
| Phase 4: Verify | 25–30 min | 30 min |

**RTO target: ≤ 30 minutes ✓**
