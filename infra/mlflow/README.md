# RailOS MLflow 2.13 — Tracking Server & Artifact Store

This directory contains Kubernetes manifests to deploy the MLflow tracking server
for the RailOS Pilot System (Tier 4 Central Core infrastructure).

## Configuration Summary

| Parameter | Value |
|-----------|-------|
| MLflow version | 2.13 |
| Replicas | 2 (zero-downtime rolling updates) |
| Backend store | PostgreSQL (Patroni cluster) — tracking metadata |
| Artifact store | MinIO (`s3://railos-mlflow-artifacts`) — model artifacts |
| S3 endpoint | `http://minio.railos.svc.cluster.local:9000` |
| Server port | 5000 (ClusterIP) |
| Namespace | `railos` |
| Model version format | `MAJOR.MINOR.PATCH` (as MLflow tag `railos_model_version`) |

MLflow satisfies **Requirement 11** (model governance and auditability) and
**Design §4.2 / §10.1** (MLflow Registry in Tier 4 with geo-replicated S3 artifacts).

---

## Directory Layout

```
infra/mlflow/
├── README.md                  # This file
├── 01-secrets.yaml            # MLflow DB password + MinIO credentials (placeholders)
├── 02-configmap.yaml          # Server config: backend URI, artifact root, server args,
│                              #   versioning tag keys, startup script
├── 03-services.yaml           # ClusterIP service on port 5000
├── 04-deployment.yaml         # MLflow 2.13 Deployment: 2 replicas, non-root,
│                              #   init containers for PostgreSQL and MinIO readiness
└── 05-prometheus-rules.yaml   # PrometheusRule: up/down, replica count, model registration rate
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Kubernetes Cluster — namespace: railos                               │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  mlflow Service (ClusterIP :5000)                           │    │
│  └──────────────────────┬──────────────────────────────────────┘    │
│                         │ load balanced                              │
│          ┌──────────────┴──────────────┐                            │
│          │                             │                             │
│  ┌───────▼──────┐           ┌──────────▼──────┐                    │
│  │ mlflow pod 0 │           │  mlflow pod 1   │                    │
│  │ :5000 HTTP   │           │  :5000 HTTP     │                    │
│  └──────────────┘           └─────────────────┘                    │
│          │                             │                             │
│          └──────────────┬──────────────┘                            │
│                         │                                            │
│          ┌──────────────▼──────────────┐                            │
│          │ PostgreSQL (Patroni)         │  ← tracking metadata      │
│          │ postgresql-primary:5432      │    (runs, params, metrics) │
│          └─────────────────────────────┘                            │
│                                                                       │
│          ┌──────────────────────────────┐                            │
│          │ MinIO (distributed EC:2)      │  ← model artifacts        │
│          │ s3://railos-mlflow-artifacts  │    (weights, plots, etc.) │
│          └──────────────────────────────┘                            │
│                                                                       │
│  Kong Gateway ← /api/v1/mlflow/* → mlflow:5000                      │
│  Prometheus   ← :5000/metrics                                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- Kubernetes 1.25+ cluster
- `railos` namespace (deploy `infra/kafka/namespace.yaml` first)
- PostgreSQL (Patroni) cluster deployed: `infra/postgresql/`
  - `mlflow` database and user must exist in PostgreSQL
- MinIO deployed: `infra/minio/`
  - `railos-mlflow-artifacts` bucket must be created
- Prometheus Operator installed (for `PrometheusRule` CRD)

---

## Deployment

### 1. Create the MLflow database and user in PostgreSQL

```bash
kubectl exec -n railos postgresql-0 -- psql -U postgres -c "
  CREATE USER mlflow WITH PASSWORD 'REPLACE_WITH_MLFLOW_DB_PASSWORD';
  CREATE DATABASE mlflow OWNER mlflow;
  GRANT ALL PRIVILEGES ON DATABASE mlflow TO mlflow;
"
```

### 2. Create the artifact bucket in MinIO

```bash
# Using the MinIO Client (mc)
kubectl exec -n railos deploy/minio-init -- mc alias set local \
  http://minio.railos.svc.cluster.local:9000 \
  "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

kubectl exec -n railos deploy/minio-init -- mc mb local/railos-mlflow-artifacts
kubectl exec -n railos deploy/minio-init -- mc anonymous set none local/railos-mlflow-artifacts
```

### 3. Set credentials

Edit `01-secrets.yaml` and replace all `REPLACE_WITH_*` values, or create the secret directly:

```bash
# Create a dedicated MinIO service account for MLflow
MINIO_MLFLOW_KEY=$(openssl rand -hex 16)
MINIO_MLFLOW_SECRET=$(openssl rand -hex 32)
MLFLOW_DB_PASSWORD=$(openssl rand -base64 24)

kubectl create secret generic mlflow-secrets \
  --namespace railos \
  --from-literal=MLFLOW_BACKEND_STORE_URI="postgresql+psycopg2://mlflow:${MLFLOW_DB_PASSWORD}@postgresql-primary.railos.svc.cluster.local:5432/mlflow" \
  --from-literal=MLFLOW_DB_PASSWORD="${MLFLOW_DB_PASSWORD}" \
  --from-literal=MLFLOW_ARTIFACT_ROOT="s3://railos-mlflow-artifacts" \
  --from-literal=AWS_ACCESS_KEY_ID="${MINIO_MLFLOW_KEY}" \
  --from-literal=AWS_SECRET_ACCESS_KEY="${MINIO_MLFLOW_SECRET}"
```

**Production note:** Populate secrets via HashiCorp Vault Agent Injector or External Secrets
Operator pointing at `secret/railos/mlflow/*` in Vault. Do not commit credentials to source control.

### 4. Apply manifests in order

```bash
kubectl apply -f infra/mlflow/01-secrets.yaml      # skip if using Vault
kubectl apply -f infra/mlflow/02-configmap.yaml
kubectl apply -f infra/mlflow/03-services.yaml
kubectl apply -f infra/mlflow/04-deployment.yaml

# Wait for rollout
kubectl rollout status deployment/mlflow -n railos --timeout=5m

# Prometheus rules
kubectl apply -f infra/mlflow/05-prometheus-rules.yaml
```

### 5. Verify deployment

```bash
# Check pod status
kubectl get pods -n railos -l app=mlflow

# Check health endpoint
kubectl exec -n railos deploy/mlflow -- curl -sf http://localhost:5000/health

# List experiments
kubectl exec -n railos deploy/mlflow -- \
  curl -sf http://localhost:5000/api/2.0/mlflow/experiments/list | python3 -m json.tool

# Verify artifact store connectivity (MinIO)
kubectl exec -n railos deploy/mlflow -- \
  python3 -c "
import boto3, os
s3 = boto3.client('s3',
  endpoint_url=os.environ['MLFLOW_S3_ENDPOINT_URL'],
  aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
  aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY']
)
print(s3.head_bucket(Bucket='railos-mlflow-artifacts'))
print('MinIO artifact bucket is accessible.')
"
```

---

## Model Versioning Convention (Requirement 11 C1)

MLflow internally assigns sequential integer version IDs (1, 2, 3, ...) to model versions.
RailOS uses the `railos_model_version` tag to store the `MAJOR.MINOR.PATCH` semantic version.

**When training a model:**
```python
import mlflow

with mlflow.start_run() as run:
    mlflow.log_params({"epochs": 50, "learning_rate": 0.001})
    mlflow.log_metrics({"loss": 0.023, "accuracy": 0.97})
    mlflow.set_tag("railos_model_version", "2.1.3")
    mlflow.set_tag("railos_requirement_id", "REQ-3")    # links to Req 3 (defect detection)
    mlflow.pytorch.log_model(model, "defect-detector")

# Register the model version
client = mlflow.MlflowClient()
mv = client.create_model_version(
    name="defect-detector",
    source=f"runs:/{run.info.run_id}/defect-detector",
    run_id=run.info.run_id
)
client.set_model_version_tag(mv.name, mv.version, "railos_model_version", "2.1.3")
```

**For Federated Learning rounds (Req 11 C4):**
```python
# Tag the global model version with the FL round ID
client.set_model_version_tag(mv.name, mv.version, "railos_fl_round_id", "round-42")
client.set_model_version_tag(mv.name, mv.version, "railos_pre_update_version", "2.0.1")
client.set_model_version_tag(mv.name, mv.version, "railos_post_update_version", "2.1.0")
```

---

## Geo-Replication

Artifact geo-replication is provided by MinIO's distributed erasure-coding mode (EC:2 across
4 pods). For true geographic redundancy across data centers, configure MinIO site replication:

```bash
# Configure MinIO site replication (requires a second MinIO cluster at a remote site)
mc admin replicate add \
  local/railos-mlflow-artifacts \
  remote/railos-mlflow-artifacts
```

See `infra/minio/README.md` for MinIO site replication configuration details.

---

## Requirement Traceability

| Manifest | Requirement | Criterion |
|----------|-------------|-----------|
| `04-deployment.yaml` | Req 11 C1 | MAJOR.MINOR.PATCH model version tags |
| `04-deployment.yaml` | Req 11 C2 | MLflow records model version, input hash, output, timestamp |
| `04-deployment.yaml` | Req 11 C4 | FL round ID and pre/post version recorded as tags |
| `04-deployment.yaml` | Req 11 C5 | 365-day retention (PostgreSQL backup policy) |
| `04-deployment.yaml` | Req 39    | Non-root, capabilities drop ALL, no privilege escalation |
| `02-configmap.yaml` | Req 11 C1 | RAILOS_MODEL_VERSION_TAG_KEY convention defined |
| `02-configmap.yaml` | Task 21.1 | RAILOS_REQUIREMENT_TAG_KEY for traceability matrix |
| `05-prometheus-rules.yaml` | Req 17 | MLflow up/down, replica count monitoring |
| `05-prometheus-rules.yaml` | Req 11 | Model registration rate alerting |
