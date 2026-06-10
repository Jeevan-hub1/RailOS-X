# RailOS InfluxDB 3.0 — Deployment & Failover Guide

This directory contains Kubernetes manifests to deploy the InfluxDB 3.0 time-series store
for the RailOS Pilot System (Tier 4 Central Core infrastructure).

## Configuration Summary

| Parameter | Value |
|-----------|-------|
| InfluxDB version | 3.0 |
| Deployment topology | Primary StatefulSet + Hot Standby StatefulSet |
| Replication method | Continuous WAL streaming (custom sidecar) |
| Replication lag target | ≤60 s (RPO requirement) |
| RTO target | < 5 min (manual failover procedure) |
| Storage per node | 500 Gi PVC (SSD-backed) |
| Namespace | `railos` |
| Retention — sensor events | 90 days (Requirement 1 C4) |
| Retention — digital twin state | 7 days |
| Retention — observability | 30 days |

These settings satisfy **Requirement 1 C4** (90-day sensor event retention),
**Requirement 8 C1** (Digital Twin real-time state store, ≤5 s refresh),
and **Requirements 15/16** (RPO ≤60 s, RTO < 5 min) from the RailOS spec,
and the HA table in **§10.1** of the design document.

---

## Directory Layout

```
infra/influxdb/
├── README.md                        # This file
├── 01-configmap.yaml                # InfluxDB config, WAL settings, retention policies
├── 02-secrets.yaml                  # Credentials template (replace before deploy)
├── 03-services.yaml                 # ClusterIP + headless services for primary and standby
├── 04-primary-statefulset.yaml      # InfluxDB 3.0 primary + wal-streamer sidecar
├── 05-standby-statefulset.yaml      # InfluxDB 3.0 standby + wal-receiver sidecar
├── 06-pdb.yaml                      # PodDisruptionBudgets for primary and standby
├── 07-setup-job.yaml                # Bootstrap Job: creates buckets, sets retention policies
├── 08-prometheus-rules.yaml         # PrometheusRule: replication lag + availability alerts
├── 09-network-policy.yaml           # NetworkPolicies restricting access to InfluxDB pods
└── wal-streamer/
    ├── Dockerfile                   # Image for wal-streamer and wal-receiver sidecars
    ├── entrypoint.sh                # Mode selector (ROLE=streamer|receiver)
    ├── wal-stream.sh                # Primary sidecar: tails WAL, streams to standby
    ├── wal-receive.sh               # Standby sidecar: receives WAL, applies to InfluxDB
    └── metrics.py                   # Prometheus metrics server for both sidecars
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Kubernetes Cluster — namespace: railos                          │
│                                                                  │
│  ┌───────────────────────────────┐  WAL stream (TCP:8088)       │
│  │  influxdb-primary-0 (pod)     │ ─────────────────────────►  │
│  │  ┌─────────────────────────┐  │                              │
│  │  │  influxdb container     │  │  ┌──────────────────────────┐│
│  │  │  :8086 HTTP API         │  │  │  influxdb-standby-0 (pod)││
│  │  │  :8088 WAL stream port  │  │  │  ┌────────────────────┐  ││
│  │  └─────────────────────────┘  │  │  │  influxdb container│  ││
│  │  ┌─────────────────────────┐  │  │  │  :8086 HTTP API    │  ││
│  │  │  wal-streamer sidecar   │  │  │  └────────────────────┘  ││
│  │  │  inotifywait → ncat     │  │  │  ┌────────────────────┐  ││
│  │  │  :9090/metrics (lag)    │◄─┼──┼─►│  wal-receiver      │  ││
│  │  └─────────────────────────┘  │  │  │  sidecar :8088     │  ││
│  │  500 Gi PVC                   │  │  │  :9091/metrics     │  ││
│  └───────────────────────────────┘  │  └────────────────────┘  ││
│                                     │  500 Gi PVC               ││
│  influxdb-primary (ClusterIP:8086)  └──────────────────────────┘│
│  influxdb-standby (ClusterIP:8086)                               │
│                                                                  │
│  Flink writers ──► influxdb-primary:8086                        │
│  Digital Twin  ──► influxdb-primary:8086 (writes + reads)       │
│                ──► influxdb-standby:8086 (read offload, optional)│
│  Prometheus    ──► :8086/metrics, :9090/metrics, :9091/metrics  │
└─────────────────────────────────────────────────────────────────┘
```

**Replication mechanism:** The `wal-streamer` sidecar on the primary watches the InfluxDB WAL
directory using `inotifywait`. When InfluxDB closes a WAL segment file, the sidecar streams
it to the standby over TCP with HMAC authentication. The `wal-receiver` sidecar on the standby
accepts the segment, validates the HMAC, writes it to the WAL directory, and calls the InfluxDB
local API to apply it.

---

## Prerequisites

- Kubernetes 1.25+ cluster
- `kubectl` configured for your cluster
- `railos` namespace already created (deploy `infra/kafka/namespace.yaml` first)
- Prometheus Operator installed (for `PrometheusRule` CRD in `08-prometheus-rules.yaml`)
  — if not using the operator, copy the `groups` block into your Prometheus config manually
- SSD-backed `StorageClass` (replace `standard` in PVC specs with your class name)
- Container registry accessible from the cluster (to push the WAL sidecar image)

---

## Step-by-Step Deployment

### 1. Build and push the WAL sidecar image

```bash
cd infra/influxdb/wal-streamer

docker build -t <your-registry>/railos/influxdb-wal-streamer:1.0.0 .
docker push <your-registry>/railos/influxdb-wal-streamer:1.0.0

# Tag for receiver (same image)
docker tag <your-registry>/railos/influxdb-wal-streamer:1.0.0 \
           <your-registry>/railos/influxdb-wal-receiver:1.0.0
docker push <your-registry>/railos/influxdb-wal-receiver:1.0.0
```

Then update the `image:` field in `04-primary-statefulset.yaml` (wal-streamer container)
and `05-standby-statefulset.yaml` (wal-receiver container) to use your registry URL.

### 2. Set credentials in the Secrets manifest

Edit `02-secrets.yaml` and replace all `REPLACE_WITH_*` values:

```bash
# Generate strong credentials
ADMIN_PASSWORD=$(openssl rand -base64 24)
ADMIN_TOKEN=$(openssl rand -hex 32)
REPLICATION_SECRET=$(openssl rand -hex 32)

# Update the secret (or use kubectl create secret directly)
kubectl create secret generic influxdb-auth \
  --namespace railos \
  --from-literal=INFLUXDB_INIT_USERNAME=railos-admin \
  --from-literal=INFLUXDB_INIT_PASSWORD="${ADMIN_PASSWORD}" \
  --from-literal=INFLUXDB_INIT_ADMIN_TOKEN="${ADMIN_TOKEN}" \
  --from-literal=INFLUXDB_INIT_ORG=railos-pilot \
  --from-literal=INFLUXDB_INIT_BUCKET=sensor_events \
  --from-literal=INFLUXDB_REPLICATION_SECRET="${REPLICATION_SECRET}"
```

**Production note:** In production, populate this Secret via HashiCorp Vault Agent Injector
or External Secrets Operator, pointing at `secret/railos/influxdb/*` in Vault. Do not commit
credentials to source control.

### 3. Update the StorageClass

Edit `04-primary-statefulset.yaml` and `05-standby-statefulset.yaml` and replace
`storageClassName: standard` with your cluster's SSD-backed storage class:

| Platform | Recommended StorageClass |
|----------|--------------------------|
| AWS EKS  | `gp3`                    |
| GKE      | `premium-rwo`            |
| AKS      | `managed-premium`        |
| On-prem  | Longhorn / Rook-Ceph SSD class |

### 4. Apply the manifests in order

```bash
# ConfigMap and Secrets
kubectl apply -f infra/influxdb/01-configmap.yaml
kubectl apply -f infra/influxdb/02-secrets.yaml   # skip if using Vault

# Services (must exist before StatefulSets reference them)
kubectl apply -f infra/influxdb/03-services.yaml

# StatefulSets
kubectl apply -f infra/influxdb/04-primary-statefulset.yaml
kubectl apply -f infra/influxdb/05-standby-statefulset.yaml

# PodDisruptionBudgets
kubectl apply -f infra/influxdb/06-pdb.yaml

# Wait for primary to be ready before running bootstrap
kubectl rollout status statefulset/influxdb-primary -n railos --timeout=5m

# Run bootstrap job (creates buckets, sets retention policies)
kubectl apply -f infra/influxdb/07-setup-job.yaml

# Wait for bootstrap to complete
kubectl wait --for=condition=complete job/influxdb-bootstrap -n railos --timeout=5m

# Prometheus alert rules (requires Prometheus Operator)
kubectl apply -f infra/influxdb/08-prometheus-rules.yaml

# Network policies
kubectl apply -f infra/influxdb/09-network-policy.yaml
```

### 5. Verify deployment

```bash
# Check primary pod status
kubectl get pods -n railos -l app=influxdb-primary

# Check standby pod status
kubectl get pods -n railos -l app=influxdb-standby

# Check primary health
kubectl exec -n railos influxdb-primary-0 -c influxdb -- \
  curl -sf http://localhost:8086/health | python3 -m json.tool

# List buckets (should show sensor_events, digital_twin_state, etc.)
INFLUX_TOKEN=$(kubectl get secret influxdb-auth -n railos \
  -o jsonpath='{.data.INFLUXDB_INIT_ADMIN_TOKEN}' | base64 -d)
kubectl exec -n railos influxdb-primary-0 -c influxdb -- \
  curl -sf -H "Authorization: Token ${INFLUX_TOKEN}" \
  http://localhost:8086/api/v2/buckets | python3 -m json.tool

# Check WAL streamer replication lag
kubectl logs -n railos influxdb-primary-0 -c wal-streamer --tail=20

# Check WAL receiver on standby
kubectl logs -n railos influxdb-standby-0 -c wal-receiver --tail=20

# Check replication lag via Prometheus metrics
kubectl exec -n railos influxdb-primary-0 -c wal-streamer -- \
  curl -sf http://localhost:9090/metrics | grep replication_lag
```

### 6. Verify replication lag ≤ 60 s

The `InfluxDBReplicationLagCritical` Prometheus alert fires when lag > 60 s.
In steady state with normal write traffic, lag should be < 5 s.

```bash
# Write a test point to primary
kubectl exec -n railos influxdb-primary-0 -c influxdb -- \
  curl -sf -X POST "http://localhost:8086/api/v2/write?org=railos-pilot&bucket=sensor_events&precision=s" \
  -H "Authorization: Token ${INFLUX_TOKEN}" \
  --data-binary 'sensor_test,node=test value=1.0'

# Query the standby ~5 seconds later to verify replication
sleep 10
kubectl exec -n railos influxdb-standby-0 -c influxdb -- \
  curl -sf -X POST "http://localhost:8086/api/v2/query?org=railos-pilot" \
  -H "Authorization: Token ${INFLUX_TOKEN}" \
  -H "Content-Type: application/vnd.flux" \
  --data 'from(bucket:"sensor_events") |> range(start:-1m) |> filter(fn:(r) => r._measurement == "sensor_test")'
```

If the standby returns data, replication is working.

---

## Internal DNS Names

| Service | DNS Name | Port | Purpose |
|---------|----------|------|---------|
| Primary HTTP API | `influxdb-primary.railos.svc.cluster.local` | 8086 | Writes + reads (Flink, Digital Twin) |
| Primary WAL stream | `influxdb-primary-0.influxdb-primary-headless.railos.svc.cluster.local` | 8088 | Internal WAL replication |
| Standby HTTP API | `influxdb-standby.railos.svc.cluster.local` | 8086 | Read offload + failover target |
| Primary metrics | Pod IP | 9090 | Prometheus scrape (wal-streamer lag) |
| Standby metrics | Pod IP | 9091 | Prometheus scrape (wal-receiver lag) |

---

## Failover Procedure (RTO Target: < 5 min)

Use this procedure when the primary pod has failed and cannot self-heal within 2 minutes.

### Automated detection

The `InfluxDBPrimaryDown` Prometheus alert fires after 30 s of the primary not being Ready.
PagerDuty/SMS notification is sent within 1 minute via Alertmanager (configured in the
observability stack, Task 1.19).

### Manual failover steps

**Time budget: complete within 5 minutes to meet RTO.**

#### Step 1 — Confirm primary is down (30 s)

```bash
kubectl get pod influxdb-primary-0 -n railos
kubectl describe pod influxdb-primary-0 -n railos
```

If the pod is in `CrashLoopBackOff` or `Pending` and does not recover after one more minute,
proceed.

#### Step 2 — Verify standby has latest data (30 s)

```bash
# Check standby health
kubectl exec -n railos influxdb-standby-0 -c influxdb -- \
  curl -sf http://localhost:8086/health

# Check last WAL segment received
kubectl logs -n railos influxdb-standby-0 -c wal-receiver --tail=5
```

Note the timestamp of the last applied WAL segment. Data after this timestamp may be lost
(bounded by RPO ≤ 60 s — this is the acceptable data loss window per Requirement 15/16).

#### Step 3 — Promote standby to primary (2 min)

```bash
# Scale down the standby StatefulSet WAL receiver to stop waiting for incoming WAL
# (prevents split-brain if primary recovers)
kubectl patch statefulset influxdb-standby -n railos \
  --type json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/1/env/0/value","value":"primary"}]'

# Update the Flink Data_Pipeline and Digital Twin deployments to point at standby:
# Patch the INFLUXDB_URL environment variable in the Flink TaskManager and
# Digital Twin deployments:
kubectl set env deployment/flink-taskmanager -n railos \
  INFLUXDB_URL=http://influxdb-standby.railos.svc.cluster.local:8086

kubectl set env deployment/digital-twin -n railos \
  INFLUXDB_URL=http://influxdb-standby.railos.svc.cluster.local:8086
```

**Verification:**

```bash
# Confirm writes are flowing to the (now promoted) standby
kubectl logs -n railos -l app=influxdb-standby -c influxdb --tail=20 | grep "write"
```

#### Step 4 — Investigate and restore original primary (after service is stable)

1. Investigate root cause of primary failure (`kubectl describe`, node events, PVC status)
2. If the PVC is intact, delete and recreate the primary pod:
   ```bash
   kubectl delete pod influxdb-primary-0 -n railos
   # StatefulSet will recreate it automatically
   ```
3. Once the new primary is healthy, reconfigure WAL streaming direction so the
   new primary begins streaming from the (former) standby's latest state.
4. Update application `INFLUXDB_URL` back to `influxdb-primary.railos.svc.cluster.local`
   after a full WAL sync is confirmed.

#### Step 5 — Update PagerDuty/operations log

Record:
- Failure timestamp
- Detected timestamp
- Failover-completed timestamp
- Data loss window (last WAL segment time → failure time)
- Root cause (to be determined from post-mortem)

---

## Retention Policy Management

Retention policies are created by the bootstrap Job (`07-setup-job.yaml`).
To change a retention policy (e.g., extend sensor events to 180 days):

```bash
INFLUX_TOKEN=$(kubectl get secret influxdb-auth -n railos \
  -o jsonpath='{.data.INFLUXDB_INIT_ADMIN_TOKEN}' | base64 -d)

# Get the bucket ID
BUCKET_ID=$(kubectl exec -n railos influxdb-primary-0 -c influxdb -- \
  curl -sf -H "Authorization: Token ${INFLUX_TOKEN}" \
  "http://localhost:8086/api/v2/buckets?org=railos-pilot&name=sensor_events" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['buckets'][0]['id'])")

# Update retention rule to 180 days (15552000 seconds)
kubectl exec -n railos influxdb-primary-0 -c influxdb -- \
  curl -sf -X PATCH "http://localhost:8086/api/v2/buckets/${BUCKET_ID}" \
  -H "Authorization: Token ${INFLUX_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"retentionRules": [{"type": "expire", "everySeconds": 15552000}]}'
```

**Note:** Retention policy changes must be authorized by the Governance_Officer role
(Requirement 28) and logged in HashiCorp Vault configuration audit trail.

---

## Storage Sizing Reference

| Bucket | Retention | Estimated Size |
|--------|-----------|----------------|
| `sensor_events` | 90 days | ~390 Gi (10k events/s × 90d × ~500 B/event compressed) |
| `digital_twin_state` | 7 days | ~5 Gi |
| `corridor_energy_efficiency` | 90 days | ~1 Gi |
| `observability_telemetry` | 30 days | ~10 Gi |
| **Total (with WAL headroom)** | — | **~500 Gi** |

500 Gi PVCs provide ~28% headroom. Monitor with:
```bash
kubectl exec -n railos influxdb-primary-0 -c influxdb -- df -h /var/lib/influxdb3
```

Alert at 80% usage (`railos_edge_storage_utilization_pct > 80` in the observability stack).

---

## Security Notes

- All pods run as non-root (UID 1000), `allowPrivilegeEscalation: false`, `capabilities drop ALL`
- NetworkPolicies restrict InfluxDB access to authorized pods only (Flink, Digital Twin, Prometheus)
- The admin token is stored in a Kubernetes Secret; in production, use Vault integration
- WAL segments are authenticated with HMAC-SHA256 using a shared replication secret
- The Standby HTTP API accepts read-only queries from the Digital Twin but does not accept
  Flink writes during normal operation (only the primary does)
- TLS termination should be added for the HTTP API in production;
  use a cert-manager `Certificate` resource targeting the `influxdb-primary` Service

---

## Upgrading InfluxDB

1. Update the `image:` tag in both StatefulSet manifests to the new version
2. Apply the standby first (no production traffic):
   ```bash
   kubectl patch statefulset influxdb-standby -n railos \
     --type json \
     -p '[{"op":"replace","path":"/spec/template/spec/containers/0/image","value":"influxdb:3.x.y"}]'
   kubectl rollout status statefulset/influxdb-standby -n railos
   ```
3. Verify standby is healthy and replication resumes
4. Apply the primary update (causes brief downtime during pod restart — typically < 60 s):
   ```bash
   kubectl patch statefulset influxdb-primary -n railos \
     --type json \
     -p '[{"op":"replace","path":"/spec/template/spec/containers/0/image","value":"influxdb:3.x.y"}]'
   kubectl rollout status statefulset/influxdb-primary -n railos
   ```
5. Monitor replication lag in Prometheus for 10 minutes post-upgrade

---

## Requirement Traceability

| Manifest | Requirement | Criterion |
|----------|-------------|-----------|
| `01-configmap.yaml` | Req 1 | C4 — 90-day retention configuration |
| `04-primary-statefulset.yaml` | Req 1 | C4, C6, C8 — primary write path |
| `04-primary-statefulset.yaml` | Req 8 | C1 — state store for Digital Twin |
| `04-primary-statefulset.yaml` | Req 15/16 | RPO ≤60s, RTO <5 min (primary node) |
| `05-standby-statefulset.yaml` | Req 15/16 | Hot standby for failover |
| `08-prometheus-rules.yaml` | Req 15/16 | Replication lag ≤60s monitoring |
| `07-setup-job.yaml` | Req 1 | C4 — bucket retention policies |
| `07-setup-job.yaml` | Design §10.4 | Retention lifecycle configuration |
| `09-network-policy.yaml` | Req 39 | IEC 62443 Zone 2 network isolation |
