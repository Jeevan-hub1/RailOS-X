# RailOS Disaster Recovery Scripts

Satisfies: **Req 15** (99.95% availability), **Req 16** (RTO ≤ 30 min, RPO ≤ 60 s)

---

## Scripts

| Script | Task | Purpose |
|--------|------|---------|
| `verify_kafka_ha.sh` | 20.1 | Verify Kafka RF=3, test broker failure + leader election |
| `verify_influxdb_replication.sh` | 20.2 | Write test measurement, verify standby replication ≤ 60 s |
| `verify_patroni_failover.sh` | 20.3 | Trigger Patroni failover, verify new primary in ≤ 2 min |
| `backup-cronjob.yaml` | 20.4 | Daily 02:00 UTC: pg_basebackup + MLflow mirror to MinIO |
| `backup-integrity-test.yaml` | 20.5 | Daily 04:00 UTC: restore + smoke-query + BACKUP_INTEGRITY_FAILURE alert |
| `test_edge_autonomous.sh` | 20.7 | Simulate central outage, verify edge autonomy + reconnect upload |

The full system restore runbook (RTO ≤ 30 min) is at [`docs/dr/RESTORE_RUNBOOK.md`](../../docs/dr/RESTORE_RUNBOOK.md).

---

## Usage

All shell scripts respect the `NAMESPACE` env var (default: `railos`).

```bash
# Mark scripts executable
chmod +x scripts/dr/*.sh

# Run individual verifications
NAMESPACE=railos ./scripts/dr/verify_kafka_ha.sh
NAMESPACE=railos ./scripts/dr/verify_influxdb_replication.sh
NAMESPACE=railos ./scripts/dr/verify_patroni_failover.sh

# Deploy backup CronJobs
kubectl apply -f scripts/dr/backup-cronjob.yaml -n railos
kubectl apply -f scripts/dr/backup-integrity-test.yaml -n railos

# Test edge autonomous operation
NAMESPACE=railos SIMULATION_WINDOW_S=30 ./scripts/dr/test_edge_autonomous.sh
```

---

## Required Secrets / Service Accounts

Before deploying backup CronJobs, create:

```bash
# MinIO credentials for backup bucket
kubectl create secret generic backup-minio-creds \
  --namespace railos \
  --from-literal=access-key=REPLACE_ME \
  --from-literal=secret-key=REPLACE_ME

# Service account with backup permissions
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: backup-job
  namespace: railos
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: backup-job-role
  namespace: railos
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/exec"]
    verbs: ["get", "list", "create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: backup-job-rolebinding
  namespace: railos
subjects:
  - kind: ServiceAccount
    name: backup-job
roleRef:
  kind: Role
  name: backup-job-role
  apiGroup: rbac.authorization.k8s.io
EOF
```
