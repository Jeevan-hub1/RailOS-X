# RailOS PostgreSQL Patroni HA — Deployment Guide

PostgreSQL 16 managed by Patroni 3.3 in a 3-node HA cluster (1 primary + 2 streaming replicas).
Deployed in the `railos` Kubernetes namespace.

## HA Targets (Design §10.1, Req 15/16)

| Metric | Target | Mechanism |
|--------|--------|-----------|
| RPO (Recovery Point Objective) | ≤ 60 s | Streaming WAL replication, `maximum_lag_on_failover=1 MiB` |
| RTO (Recovery Time Objective) | < 2 min | Patroni `ttl=30s`, `loop_wait=10s`, `retry_timeout=30s` |
| Availability during maintenance | ≥ 2/3 pods | PodDisruptionBudget `maxUnavailable=1` |
| Daily backups | Geo-replicated | CronJob → S3 (ap-south-1) |

---

## Directory Layout

```
infra/postgresql/
├── README.md                        # This file
├── 00-namespace.yaml                # railos namespace reference (apply kafka/namespace.yaml)
├── 01-secrets.yaml                  # Credentials (replace placeholders before deploy)
├── 02-configmap-patroni.yaml        # Patroni config template + entrypoint + init-db script
├── 03-configmap-sql.yaml            # SQL init scripts (DDL for all 4 databases)
├── 04-rbac.yaml                     # ServiceAccount + Role + RoleBinding for Patroni DCS
├── 05-services.yaml                 # Primary (RW), Replicas (RO), Headless, Patroni API services
├── 06-statefulset.yaml              # 3-node StatefulSet with postgres_exporter sidecar
├── 07-pdb.yaml                      # PodDisruptionBudget (maxUnavailable=1)
├── 08-prometheus-rules.yaml         # Alerting rules (replication lag, cluster health, storage)
├── 09-network-policy.yaml           # NetworkPolicy (default-deny + explicit allow rules)
└── 10-backup-cronjob.yaml           # Daily backup CronJob + S3 credentials Secret
```

---

## Databases Created

| Database | Purpose | Append-Only Tables |
|----------|---------|--------------------|
| `railos_audit` | Security anomaly audit log, ML inference audit, authorization audit, system events | All 4 tables — `prevent_audit_mutation()` trigger blocks UPDATE/DELETE |
| `railos_hazard` | Safety hazard register | `hazard_register` — new status entries are inserted as new rows (event-sourced) |
| `railos_registry` | Asset registry (track segments, locos, sensors, etc.) | `asset_maintenance_history` — append-only; `asset_registry` itself is mutable |
| `railos_traceability` | ML model traceability matrix, data lineage | `traceability_matrix` — append-only; `model_registry` status field is updatable |

### Append-Only Enforcement

Every restricted table has two triggers:
```sql
-- Prevents UPDATE
CREATE TRIGGER trg_<table>_no_update
  BEFORE UPDATE ON <table>
  FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

-- Prevents DELETE
CREATE TRIGGER trg_<table>_no_delete
  BEFORE DELETE ON <table>
  FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
```
The application user (`railos_app`) is also granted `SELECT, INSERT` only — no `UPDATE` or `DELETE` at the PostgreSQL permission level. This provides defence-in-depth beyond the trigger layer.

---

## Prerequisites

- Kubernetes 1.25+ cluster with at least **3 nodes** (anti-affinity requires one pod per node)
- `kubectl` configured and pointing at your cluster
- `railos` namespace created (`kubectl apply -f infra/kafka/namespace.yaml`)
- An SSD-backed `StorageClass` (replace `standard` in `06-statefulset.yaml`)
- Prometheus Operator installed (for `08-prometheus-rules.yaml`); skip if using standalone Prometheus
- S3 bucket (`railos-postgresql-backups`) in `ap-south-1` (or update the region/endpoint for MinIO)

---

## Step-by-Step Deployment

### 1. Replace secrets

Open `01-secrets.yaml` and replace the base64 placeholder values with real passwords:

```bash
# Generate a strong password and encode it
echo -n 'your-strong-superuser-password' | base64
echo -n 'your-strong-replication-password' | base64
echo -n 'your-strong-patroni-api-password' | base64
echo -n 'your-strong-app-password' | base64
```

Update the `DATA_SOURCE_NAME` in `01-secrets.yaml` for the postgres_exporter:
```
postgresql://exporter:<app-password>@localhost:5432/postgres?sslmode=disable
```

Also update `10-backup-cronjob.yaml` with real AWS/MinIO credentials.

> **Production note**: Use [External Secrets Operator](https://external-secrets.io/) or
> HashiCorp Vault Agent Injector (Req 37) instead of storing secrets in this file.

### 2. Update storage class

Edit `06-statefulset.yaml` and change `storageClassName: standard` to your cluster's SSD-backed class:

| Cloud | Storage Class |
|-------|--------------|
| AWS EKS | `gp3` |
| GKE | `premium-rwo` |
| AKS | `managed-premium` |
| On-prem (Rook/Ceph) | `rook-ceph-block` |

### 3. Apply manifests in order

```bash
# Namespace (if not already created by Kafka deployment)
kubectl apply -f infra/kafka/namespace.yaml

# Credentials
kubectl apply -f infra/postgresql/01-secrets.yaml

# ConfigMaps (Patroni config + SQL init scripts)
kubectl apply -f infra/postgresql/02-configmap-patroni.yaml
kubectl apply -f infra/postgresql/03-configmap-sql.yaml

# RBAC (ServiceAccount + Role + RoleBinding for Patroni DCS)
kubectl apply -f infra/postgresql/04-rbac.yaml

# Services
kubectl apply -f infra/postgresql/05-services.yaml

# StatefulSet (starts the 3-node cluster)
kubectl apply -f infra/postgresql/06-statefulset.yaml

# Pod Disruption Budget
kubectl apply -f infra/postgresql/07-pdb.yaml

# Prometheus alerting rules (requires prometheus-operator)
kubectl apply -f infra/postgresql/08-prometheus-rules.yaml

# Network policies
kubectl apply -f infra/postgresql/09-network-policy.yaml

# Daily backup CronJob
kubectl apply -f infra/postgresql/10-backup-cronjob.yaml
```

Or apply all at once (order is preserved by filename prefix):
```bash
kubectl apply -f infra/postgresql/ --recursive
```

### 4. Watch the cluster come up

```bash
# Watch pods — node 0 bootstraps first, then 1 and 2 clone from it
kubectl get pods -n railos -l app=postgresql-patroni -w

# Expected sequence:
#   postgresql-patroni-0: Running (becomes primary)
#   postgresql-patroni-1: Running (streaming replica)
#   postgresql-patroni-2: Running (streaming replica)
```

Node 0 will:
1. Initialize PostgreSQL with `initdb`
2. Create superuser, replicator, and railos_app accounts
3. Run `init-db.sh` to create all 4 databases with their schema

Nodes 1 and 2 will:
1. Wait for node 0 to be ready
2. Clone the primary using `pg_basebackup`
3. Start streaming WAL replication

This takes approximately 2–5 minutes on first boot.

### 5. Verify the cluster

```bash
# Check Patroni cluster status via REST API
kubectl exec -n railos postgresql-patroni-0 -- \
  curl -s http://localhost:8008/cluster | python3 -m json.tool

# Verify primary election
kubectl get endpoints postgresql-primary -n railos -o json | jq '.subsets[].addresses[].targetRef.name'

# Check replication lag on replicas
kubectl exec -n railos postgresql-patroni-0 -- \
  psql -U postgres -c "SELECT client_addr, state, sent_lsn, replay_lsn,
    (sent_lsn - replay_lsn) AS lag_bytes
   FROM pg_stat_replication;"

# Verify databases exist
kubectl exec -n railos postgresql-patroni-0 -- \
  psql -U postgres -c "\l"

# Verify append-only triggers on audit table
kubectl exec -n railos postgresql-patroni-0 -- \
  psql -U postgres -d railos_audit -c "\dT+ prevent_audit_mutation"

# Test that UPDATE is blocked on an audit table
kubectl exec -n railos postgresql-patroni-0 -- \
  psql -U postgres -d railos_audit -c \
  "INSERT INTO security_anomaly_audit (event_id, iec62443_zone, reconstruction_error, threshold_value, timestamp_utc)
   VALUES (gen_random_uuid(), 'Zone2', 0.95, 0.80, now());"

kubectl exec -n railos postgresql-patroni-0 -- \
  psql -U postgres -d railos_audit -c \
  "UPDATE security_anomaly_audit SET iec62443_zone='Zone1' WHERE id=1;"
# Expected: ERROR: Audit table 'security_anomaly_audit' is append-only
```

---

## Connecting to the Cluster

### From within the Kubernetes cluster

```
Primary (read/write):  postgresql-primary.railos.svc.cluster.local:5432
Replicas (read-only):  postgresql-replicas.railos.svc.cluster.local:5432
```

### Connection string examples

```
# Primary (application writes, audit log inserts)
postgresql://railos_app:<password>@postgresql-primary.railos.svc.cluster.local:5432/railos_audit

# Replica (read queries, Grafana dashboards, analytics)
postgresql://railos_app:<password>@postgresql-replicas.railos.svc.cluster.local:5432/railos_audit?target_session_attrs=any
```

### Port-forward for local access

```bash
# Forward primary to localhost:5432
kubectl port-forward -n railos svc/postgresql-primary 5432:5432

# Forward Patroni API to localhost:8008
kubectl port-forward -n railos svc/patroni-api 8008:8008
```

---

## Failover Procedures

### Automatic Failover (Normal Case)

When the primary pod fails or becomes unresponsive:

1. Patroni detects loss of the leader key (TTL=30s, checked every loop_wait=10s)
2. Replicas race to acquire the leader lock; the most up-to-date replica wins
3. Winner promotes itself (`pg_promote()`)
4. Patroni updates the `role=master` pod label → `postgresql-primary` service redirects traffic
5. The demoted original primary, when it recovers, rejoins as a replica via `pg_rewind`

Expected timeline: **leader loss detected within 30s, promotion complete within 60–90s, total RTO < 2 min**.

Monitor failover:
```bash
# Watch Patroni cluster state in real-time
watch -n 2 'kubectl exec -n railos postgresql-patroni-0 -- curl -s http://localhost:8008/cluster | python3 -m json.tool'

# Watch pod label changes
kubectl get pods -n railos -l app=postgresql-patroni --show-labels -w
```

### Manual Switchover (Planned Maintenance)

Use `patronictl` to perform a zero-downtime switchover (old primary becomes replica, a replica becomes new primary):

```bash
# Run patronictl inside any cluster pod
kubectl exec -it -n railos postgresql-patroni-0 -- bash

# Inside the pod:
patronictl -c /etc/patroni/patroni.yaml list
# Example output:
# + Cluster: railos-postgres --------+---------+-----------+----+-----------+
# | Member               | Host      | Role    | State   | TL | Lag in MB |
# +----------------------+-----------+---------+---------+----+-----------+
# | postgresql-patroni-0 | 10.0.0.10 | Leader  | running |  1 |           |
# | postgresql-patroni-1 | 10.0.0.11 | Replica | running |  1 |         0 |
# | postgresql-patroni-2 | 10.0.0.12 | Replica | running |  1 |         0 |
# +----------------------+-----------+---------+---------+----+-----------+

# Switchover to a specific member
patronictl -c /etc/patroni/patroni.yaml switchover railos-postgres \
  --master postgresql-patroni-0 \
  --candidate postgresql-patroni-1 \
  --scheduled now
```

### Manual Failover (Emergency)

If the primary is permanently lost and Patroni cannot self-recover:

```bash
# Force failover to a specific replica
kubectl exec -it -n railos postgresql-patroni-1 -- \
  patronictl -c /etc/patroni/patroni.yaml failover railos-postgres \
  --master postgresql-patroni-0 \
  --candidate postgresql-patroni-1 \
  --force
```

### Reinstate a Recovered Node

After a failed primary recovers, Patroni will attempt to reintegrate it automatically using `pg_rewind`.
If manual reinstatement is needed:

```bash
kubectl exec -it -n railos postgresql-patroni-0 -- \
  patronictl -c /etc/patroni/patroni.yaml reinit railos-postgres postgresql-patroni-0 --force
```

---

## Backup and Restore

### Verify a backup was created

```bash
# Check backup CronJob history
kubectl get jobs -n railos -l app=postgresql-backup

# View backup job logs
kubectl logs -n railos job/<job-name>

# List backup files in S3
aws s3 ls s3://railos-postgresql-backups/postgresql/ --recursive
```

### Restore a database from backup

```bash
# Port-forward to primary
kubectl port-forward -n railos svc/postgresql-primary 5432:5432 &

# Download the backup from S3
aws s3 cp s3://railos-postgresql-backups/postgresql/<TIMESTAMP>/railos_audit_<TIMESTAMP>.dump \
  ./railos_audit.dump

# Restore (drop and recreate the database first if needed)
pg_restore \
  --host=localhost --port=5432 \
  --username=postgres \
  --dbname=railos_audit \
  --clean --if-exists \
  ./railos_audit.dump
```

> **Note**: Restoring to the primary will replicate the changes to all replicas via streaming replication.

---

## Scaling

### Add a fourth replica

The StatefulSet can be scaled up with:

```bash
kubectl scale statefulset postgresql-patroni -n railos --replicas=4
```

The new pod will clone from the primary and automatically join as a streaming replica.
Remember to also relax the PodDisruptionBudget if 4 replicas are deployed:

```bash
kubectl patch pdb postgresql-patroni-pdb -n railos \
  --type merge -p '{"spec":{"maxUnavailable":1}}'
```

---

## Security Notes

- All pods run as UID 999 (postgres), non-root, with `allowPrivilegeEscalation: false` and all capabilities dropped.
- The `railos_app` user has `INSERT` only on audit tables at the PostgreSQL permission level, in addition to the trigger-based append-only enforcement.
- Network access is restricted by NetworkPolicy to the `railos` namespace (application traffic) and the `monitoring` namespace (Prometheus scraping only).
- In production, replace the Secret objects in this directory with External Secrets Operator or HashiCorp Vault Agent Injector references (Req 37).
- Enable TLS on PostgreSQL connections by adding `ssl = on` to the Patroni DCS `postgresql.parameters` block and mounting a certificate Secret.

---

## Prometheus Metrics

The `postgres_exporter` sidecar exposes metrics on `:9187/metrics` of every pod.
Key metrics for observability:

| Metric | Description |
|--------|-------------|
| `pg_up` | 1 if postgres is reachable, 0 otherwise |
| `pg_replication_lag_seconds` | WAL replay lag on replicas (RPO monitoring) |
| `pg_stat_activity_count` | Active connections |
| `pg_database_size_bytes` | Per-database size |
| `pg_replication_slots_active` | Physical replication slot health |
| `pg_stat_bgwriter_*` | Background writer performance |

The `08-prometheus-rules.yaml` file defines alerting rules for:
- Replication lag > 30s (warning) and > 60s (critical, RPO breach)
- Pod count < 3 (degraded) and < 2 (critical, no HA)
- No master detected (critical)
- PVC usage > 80% (warning) and > 95% (critical)
- postgres_exporter down

---

## Troubleshooting

### Pods stuck in Init or Pending

```bash
kubectl describe pod postgresql-patroni-0 -n railos
# Check: node affinity (requires 3 separate nodes), PVC binding, image pull
```

### Patroni in "no leader" state

```bash
# Check DCS state (ConfigMap/Endpoint in railos namespace)
kubectl get configmap -n railos | grep patroni
kubectl get endpoints -n railos postgresql-primary

# Check Patroni logs
kubectl logs -n railos postgresql-patroni-0 -c postgresql-patroni | tail -50
```

### Replication lag is high

```bash
# Check WAL sender on primary
kubectl exec -n railos postgresql-patroni-0 -- \
  psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Check WAL receiver on replica
kubectl exec -n railos postgresql-patroni-1 -- \
  psql -U postgres -c "SELECT * FROM pg_stat_wal_receiver;"
```

### Backup job failed

```bash
kubectl logs -n railos job/postgresql-daily-backup-<timestamp>
# Common causes: wrong PGPASSWORD, S3 credentials, bucket permissions, disk space
```

### Verify append-only triggers are installed

```bash
kubectl exec -n railos postgresql-patroni-0 -- \
  psql -U postgres -d railos_audit -c \
  "SELECT trigger_name, event_manipulation, action_statement
   FROM information_schema.triggers
   WHERE trigger_schema='public'
   ORDER BY trigger_name;"
```

---

## Requirements Traceability

| Requirement | How Satisfied |
|-------------|---------------|
| Req 9 C7 | `security_anomaly_audit` table in `railos_audit`; append-only triggers + REVOKE UPDATE/DELETE |
| Req 11 C5 | `model_inference_audit` table; 365-day `retain_until` column; append-only |
| Req 12 C4/C5 | `authorization_audit` table; append-only triggers; `railos_app` has INSERT only |
| Req 15 | 3-node StatefulSet, Patroni HA, `07-pdb.yaml` (maxUnavailable=1) |
| Req 16 C2 | WAL streaming, `maximum_lag_on_failover=1MiB`, Prometheus lag alert at 60s |
| Req 16 C3 | Daily CronJob (`10-backup-cronjob.yaml`) → S3 `ap-south-1` |
| Req 17 | `postgres_exporter` sidecar on `:9187`, `08-prometheus-rules.yaml` |
| Design §9.5 | `prevent_audit_mutation()` trigger on all audit/hazard tables |
| Design §10.1 | Patroni `ttl=30s`, `loop_wait=10s` → RTO < 2 min, RPO ≤ 60s |
| Design §10.2 | Daily backup CronJob + `BACKUP_INTEGRITY_FAILURE` alert rule |
| Design §13.1 | `traceability_matrix` and `data_lineage` tables in `railos_traceability` |
| Design §13.2 | `hazard_register` table in `railos_hazard`; append-only |
