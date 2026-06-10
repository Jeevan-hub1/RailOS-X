# RailOS Flink Stream Processing Cluster — Deployment Guide

This directory contains Kubernetes manifests to deploy an Apache Flink 1.18 cluster for the
RailOS Pilot System (Tier 4 Central Core, Zone 2 data pipeline infrastructure).

The Flink cluster reads from Kafka sensor topics, performs stream processing (feature extraction,
stream joins, anomaly rule evaluation, schema validation routing), and writes to InfluxDB 3.0
and Delta Lake (S3-compatible MinIO).

---

## Configuration Summary

| Parameter | Value |
|-----------|-------|
| Flink version | 1.18.1 (Scala 2.12, Java 11) |
| JobManager replicas | 1 (Kubernetes-native HA via ConfigMap leases) |
| TaskManager replicas | 3 |
| Task slots per TM | 4 |
| Total task slots | 12 |
| Default parallelism | 12 |
| State backend | RocksDB (incremental checkpoints) |
| Checkpoint interval | 10 s (EXACTLY_ONCE) |
| Checkpoint storage | PVC `flink-checkpoints` (100 Gi) + per-TM RocksDB PVC (50 Gi each) |
| Metrics | Prometheus reporter on port 9249 |
| Namespace | `railos` |

These settings satisfy:
- **Requirement 1 C2** — 500 ms normalization SLA (10 s checkpoint interval, RocksDB state)
- **Requirement 1 C6** — 10,000 events/s throughput (12 parallel task slots)
- **Requirement 1 C3/C7** — Schema validation routing to dead-letter topics (Flink job logic)
- **Design §4.2** — Flink cluster on Kubernetes (Job Manager + Task Managers)

---

## Directory Layout

```
infra/flink/
├── README.md                          # This file
├── 00-rbac.yaml                       # ServiceAccount + Role + RoleBinding (Kubernetes-native HA)
├── 01-configmap.yaml                  # flink-conf.yaml + log4j2.properties
├── 02-secrets.yaml                    # Kafka, InfluxDB, Delta Lake credentials (placeholders)
├── 03-pvc.yaml                        # Shared checkpoint PVC (100 Gi)
├── 04-services.yaml                   # JM RPC, JM REST, JM BLOB, TM metrics services
├── 05-jobmanager-deployment.yaml      # JobManager Deployment (1 replica, Kubernetes HA)
├── 06-taskmanager-statefulset.yaml    # TaskManager StatefulSet (3 replicas, 4 slots each)
├── 07-poddisruptionbudget.yaml        # PDB: JM maxUnavailable=0, TM maxUnavailable=1
├── 08-prometheus-rules.yaml           # PrometheusRule CRD for alerting (Prometheus Operator)
└── 09-network-policy.yaml             # Ingress/Egress NetworkPolicies (IEC 62443 Zone 2)
```

---

## Prerequisites

- Kubernetes 1.25+ cluster
- `kubectl` configured for your cluster
- Namespace `railos` already created (`kubectl apply -f infra/kafka/namespace.yaml`)
- Kafka cluster running in the `railos` namespace (infra/kafka/)
- InfluxDB running in the `railos` namespace (infra/influxdb/)
- MinIO (or S3) accessible for Delta Lake sink and optional S3 checkpointing
- (Optional) Prometheus Operator for `PrometheusRule` CRD support

---

## Deployment Steps

### 1. Update secrets

Before deploying, replace placeholder values in `02-secrets.yaml`:

```bash
# Replace INFLUXDB_TOKEN with the actual InfluxDB operator token
# (matches INFLUXDB_INIT_ADMIN_TOKEN in infra/influxdb/02-secrets.yaml)

# Replace DELTA_LAKE_ACCESS_KEY / DELTA_LAKE_SECRET_KEY with your MinIO/S3 credentials
```

In production, use External Secrets Operator or the Vault Agent Injector instead of editing
the file directly:

```yaml
# Example ExternalSecret (requires External Secrets Operator)
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: flink-influxdb-config
  namespace: railos
spec:
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: flink-influxdb-config
  data:
    - secretKey: INFLUXDB_TOKEN
      remoteRef:
        key: secret/railos/influxdb/operator-token
        property: token
```

### 2. Apply all manifests (ordered)

```bash
# From the workspace root d:\New folder (4)\
kubectl apply -f infra/flink/00-rbac.yaml
kubectl apply -f infra/flink/01-configmap.yaml
kubectl apply -f infra/flink/02-secrets.yaml
kubectl apply -f infra/flink/03-pvc.yaml
kubectl apply -f infra/flink/04-services.yaml
kubectl apply -f infra/flink/05-jobmanager-deployment.yaml
kubectl apply -f infra/flink/06-taskmanager-statefulset.yaml
kubectl apply -f infra/flink/07-poddisruptionbudget.yaml
kubectl apply -f infra/flink/08-prometheus-rules.yaml   # Requires Prometheus Operator
kubectl apply -f infra/flink/09-network-policy.yaml
```

Or apply the whole directory in one pass:

```bash
kubectl apply -f infra/flink/
```

### 3. Wait for the cluster to become ready

```bash
# Watch the JobManager come up
kubectl rollout status deployment/flink-jobmanager -n railos --timeout=120s

# Watch TaskManagers (StatefulSet)
kubectl rollout status statefulset/flink-taskmanager -n railos --timeout=180s

# Confirm all pods are Running
kubectl get pods -n railos -l app=flink
```

Expected output:
```
NAME                               READY   STATUS    RESTARTS   AGE
flink-jobmanager-<hash>            1/1     Running   0          2m
flink-taskmanager-0                1/1     Running   0          2m
flink-taskmanager-1                1/1     Running   0          2m
flink-taskmanager-2                1/1     Running   0          2m
```

### 4. Verify cluster health

```bash
# Port-forward the Flink REST API to your local machine
kubectl port-forward svc/flink-jobmanager-rest -n railos 8081:8081

# Check cluster overview (in another terminal)
curl http://localhost:8081/overview | jq .
```

Expected response (abbreviated):
```json
{
  "taskmanagers": 3,
  "slots-total": 12,
  "slots-available": 12,
  "jobs-running": 0,
  "flink-version": "1.18.1"
}
```

---

## Job Submission

### Using the Flink CLI (via kubectl exec)

```bash
# Copy a job JAR into the JobManager pod
JM_POD=$(kubectl get pod -n railos -l app=flink,component=jobmanager -o jsonpath='{.items[0].metadata.name}')
kubectl cp target/railos-stream-processor-1.0.0.jar railos/${JM_POD}:/tmp/railos-stream-processor.jar

# Submit the sensor validation + routing job
kubectl exec -n railos ${JM_POD} -- \
  /opt/flink/bin/flink run \
    --jobmanager localhost:8081 \
    --parallelism 12 \
    --class com.railos.flink.SensorValidationJob \
    /tmp/railos-stream-processor.jar \
    --kafka.bootstrap.servers "${KAFKA_BOOTSTRAP_SERVERS}" \
    --kafka.consumer.group railos-flink-stream-processor \
    --influxdb.url "${INFLUXDB_URL}" \
    --influxdb.token "${INFLUXDB_TOKEN}"
```

### Using the REST API

```bash
# Upload the JAR
curl -X POST http://localhost:8081/jars/upload \
  -H "Expect:" \
  -F "jarfile=@target/railos-stream-processor-1.0.0.jar"
# → returns {"filename": "/tmp/flink-.../<jar-id>.jar", "status": "success"}

# Submit a job with the uploaded JAR ID
JAR_ID="<jar-id from upload response>"
curl -X POST "http://localhost:8081/jars/${JAR_ID}/run" \
  -H "Content-Type: application/json" \
  -d '{
    "entryClass": "com.railos.flink.SensorValidationJob",
    "parallelism": 12,
    "programArgsList": [
      "--kafka.bootstrap.servers", "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092",
      "--kafka.consumer.group", "railos-flink-stream-processor"
    ]
  }'
```

### Triggering a savepoint before job upgrade

```bash
JOB_ID="<running job ID from /jobs endpoint>"

# Trigger savepoint
curl -X POST "http://localhost:8081/jobs/${JOB_ID}/savepoints" \
  -H "Content-Type: application/json" \
  -d '{"cancel-job": false, "target-directory": "file:///flink/checkpoints/savepoints"}'

# Resume from savepoint after deploying new JAR
curl -X POST "http://localhost:8081/jars/${NEW_JAR_ID}/run" \
  -H "Content-Type: application/json" \
  -d '{
    "entryClass": "com.railos.flink.SensorValidationJob",
    "parallelism": 12,
    "savepointPath": "file:///flink/checkpoints/savepoints/savepoint-<id>"
  }'
```

---

## Scaling TaskManagers

To scale the number of TaskManagers (and therefore total task slots):

```bash
# Scale to 5 TaskManagers (5 × 4 = 20 slots)
kubectl scale statefulset flink-taskmanager -n railos --replicas=5

# Update parallelism in ConfigMap and restart if needed
kubectl patch configmap flink-config -n railos \
  --type merge \
  -p '{"data": {"flink-conf.yaml": "parallelism.default: 20\n..."}}'
```

To change slots per TaskManager, update `taskmanager.numberOfTaskSlots` in `01-configmap.yaml`
and perform a rolling restart of the TaskManager StatefulSet.

---

## Checkpoint Storage Options

### Option A — PVC-backed (default, this manifests)

The default configuration uses the `flink-checkpoints` PVC (100 Gi) for checkpoint state and
per-TM PVCs (50 Gi each) for RocksDB local state. This works for single-zone clusters.

```yaml
# In 01-configmap.yaml (already configured)
state.checkpoints.dir: file:///flink/checkpoints/state
state.savepoints.dir: file:///flink/checkpoints/savepoints
```

### Option B — S3-backed (recommended for production multi-zone)

For production deployments with multi-zone availability, replace the PVC with S3:

```yaml
# In 01-configmap.yaml
state.checkpoints.dir: s3://railos-flink-checkpoints/state
state.savepoints.dir: s3://railos-flink-checkpoints/savepoints
high-availability.storageDir: s3://railos-flink-checkpoints/ha

# Also add S3 plugin configuration:
s3.endpoint: http://minio.railos.svc.cluster.local:9000
s3.access-key: ${DELTA_LAKE_ACCESS_KEY}
s3.secret-key: ${DELTA_LAKE_SECRET_KEY}
s3.path.style.access: true
```

Then remove `03-pvc.yaml` and the `flink-checkpoints` volume mount from
`05-jobmanager-deployment.yaml`, and remove the `flink-rocksdb` volumeClaimTemplate from
`06-taskmanager-statefulset.yaml` (or keep it for local RocksDB temp files).

---

## Prometheus Metrics

Flink exposes Prometheus metrics on port 9249 of every pod (JobManager and TaskManagers).

Key metrics for RailOS SLA monitoring:

| Metric | SLA |
|--------|-----|
| `flink_taskmanager_job_latency_source_id_*_p95` | < 500 ms (Req 1 C2) |
| `flink_taskmanager_job_task_operator_KafkaSourceReader_KafkaConsumer_records_lag_max` | < 5,000 records |
| `flink_jobmanager_job_numRestarts` | 0 in steady state |
| `flink_jobmanager_job_lastCheckpointDuration` | < 30,000 ms |
| `flink_jobmanager_numRegisteredTaskManagers` | 3 (or configured replica count) |

Alerting rules are defined in `08-prometheus-rules.yaml` (requires Prometheus Operator).

---

## Security Notes

- All Flink pods run as UID/GID 9999 (non-root) with `allowPrivilegeEscalation: false`
  and all Linux capabilities dropped (Design §9.3, Req 39).
- The `flink` ServiceAccount has the minimum RBAC permissions required for
  Kubernetes-native HA (ConfigMap leases + Pod list/watch).
- NetworkPolicies (`09-network-policy.yaml`) restrict Flink egress to only Kafka, InfluxDB,
  MinIO, the Kubernetes API server, and DNS (IEC 62443 Zone 2, Req 23).
- Secrets are placeholder values — replace with HashiCorp Vault-managed secrets in
  production (Req 37, Req 39).
- TLS for Flink's internal and REST channels is disabled by default. Enable in production
  by setting `security.ssl.internal.enabled: true` and `security.ssl.rest.enabled: true`
  in `01-configmap.yaml` and mounting cert-manager certificates.

---

## Troubleshooting

```bash
# Inspect JobManager logs
kubectl logs -n railos -l app=flink,component=jobmanager --tail=100

# Inspect a specific TaskManager
kubectl logs -n railos flink-taskmanager-0 --tail=100

# Check Kubernetes-native HA ConfigMap leases
kubectl get configmaps -n railos -l app=flink

# Describe PVC health
kubectl describe pvc flink-checkpoints -n railos
kubectl describe pvc flink-rocksdb-flink-taskmanager-0 -n railos

# Flink REST API — list running jobs
kubectl port-forward svc/flink-jobmanager-rest -n railos 8081:8081 &
curl http://localhost:8081/jobs | jq .

# Flink REST API — check TaskManager list
curl http://localhost:8081/taskmanagers | jq .
```
