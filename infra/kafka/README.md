# RailOS Kafka Cluster — Deployment Guide

This directory contains Kubernetes manifests to deploy a production-ready Apache Kafka cluster
for the RailOS Pilot System (Tier 4 Central Core infrastructure).

## Configuration Summary

| Parameter | Value |
|-----------|-------|
| Brokers | 3 |
| Replication factor | 3 |
| `min.insync.replicas` | 2 |
| Kafka version | 3.7.0 |
| Deployment method | Strimzi Operator (primary) or plain StatefulSet (fallback) |
| Storage per broker | 200 Gi PersistentVolumeClaim |
| Namespace | `railos` |

These settings satisfy **Requirement 15 / 16** (RPO = 0, RTO < 30 s on leader election) and
the HA table in §10.1 of the design document.

---

## Directory Layout

```
infra/kafka/
├── README.md                         # This file
├── namespace.yaml                    # railos namespace
│
├── strimzi/                          # Recommended: Strimzi Operator deployment
│   ├── 00-strimzi-operator.yaml      # Strimzi CRD + operator install (namespace-scoped)
│   ├── 01-kafka-cluster.yaml         # Kafka custom resource (3 brokers, RF=3, mir=2)
│   └── 02-kafka-topics.yaml          # All RailOS Kafka topics with correct RF settings
│
└── plain/                            # Alternative: plain Kubernetes StatefulSet
    ├── 01-configmap.yaml             # Broker server.properties
    ├── 02-services.yaml              # Headless service + client service
    ├── 03-statefulset.yaml           # 3-replica Kafka StatefulSet
    └── 04-poddisruptionbudget.yaml   # PodDisruptionBudget (maxUnavailable=1)
```

---

## Option A — Strimzi Operator (Recommended)

Strimzi is a CNCF project that manages Kafka on Kubernetes via CRDs. It handles rolling
upgrades, TLS, RBAC, and certificate rotation automatically.

### Prerequisites

- Kubernetes 1.25+ cluster
- `kubectl` configured for your cluster
- Cluster-admin rights (for CRD installation)

### Steps

#### 1. Create the namespace

```bash
kubectl apply -f infra/kafka/namespace.yaml
```

#### 2. Install the Strimzi operator

The manifest `00-strimzi-operator.yaml` installs Strimzi 0.40 scoped to the `railos` namespace.
For a cluster-wide installation, replace `STRIMZI_NAMESPACE` with `*`.

```bash
kubectl apply -f infra/kafka/strimzi/00-strimzi-operator.yaml
# Wait for operator pod to become Ready
kubectl wait --for=condition=Ready pod -l name=strimzi-cluster-operator \
  -n railos --timeout=120s
```

#### 3. Deploy the Kafka cluster

```bash
kubectl apply -f infra/kafka/strimzi/01-kafka-cluster.yaml
# Watch broker pods come up (takes ~2-3 minutes)
kubectl get pods -n railos -l strimzi.io/cluster=railos-kafka -w
```

Wait until all 3 broker pods and 3 ZooKeeper pods (if using ZooKeeper mode) are `Running/Ready`.

#### 4. Create RailOS topics

```bash
kubectl apply -f infra/kafka/strimzi/02-kafka-topics.yaml
```

#### 5. Verify the cluster

```bash
# Check cluster status
kubectl get kafka railos-kafka -n railos -o jsonpath='{.status.conditions}' | jq .

# List topics
kubectl get kafkatopics -n railos

# Run a quick producer/consumer smoke test
kubectl run kafka-test --image=quay.io/strimzi/kafka:0.40.0-kafka-3.7.0 \
  --restart=Never -n railos -- \
  bin/kafka-topics.sh --bootstrap-server railos-kafka-kafka-bootstrap:9092 --list
```

---

## Option B — Plain StatefulSet (Fallback)

Use this if you cannot install CRDs (e.g., restricted cluster environments).

### Steps

```bash
kubectl apply -f infra/kafka/namespace.yaml
kubectl apply -f infra/kafka/plain/01-configmap.yaml
kubectl apply -f infra/kafka/plain/02-services.yaml
kubectl apply -f infra/kafka/plain/03-statefulset.yaml
kubectl apply -f infra/kafka/plain/04-poddisruptionbudget.yaml

# Watch pods
kubectl get pods -n railos -l app=kafka -w
```

---

## Storage Requirements

Each broker requests a **200 Gi** PVC (`storageClassName: standard` by default).
Replace `standard` with your cluster's storage class (e.g., `gp3`, `fast-ssd`).

Total storage: 3 × 200 Gi = **600 Gi**

---

## Networking

| Service | Type | Port | Purpose |
|---------|------|------|---------|
| `railos-kafka-kafka-bootstrap` | ClusterIP | 9092 | Plain client access (internal) |
| `railos-kafka-kafka-bootstrap` | ClusterIP | 9093 | TLS client access (Strimzi) |
| `railos-kafka-kafka-brokers` | Headless | 9092 | Broker-to-broker, direct pod DNS |

Internal DNS for producers/consumers: `railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092`

---

## Topic Configuration

All topics are created with `replication.factor=3` and `min.insync.replicas=2`.
See `strimzi/02-kafka-topics.yaml` for the full list matching §4.1 of the design document.

---

## Security Notes

- In production, enable TLS by setting `tls: {}` on the Kafka listener (already configured in
  the Strimzi CR under the `tls` listener on port 9093).
- Rotate TLS certificates using Strimzi's built-in cert manager integration.
- Apply Kubernetes NetworkPolicies to restrict Kafka access to the `railos` namespace only.
- The broker pods run as non-root (UID 1000) with `readOnlyRootFilesystem` disabled only for
  Kafka's log directory; all other paths are read-only.

---

## Upgrading Kafka

With Strimzi, rolling upgrades are handled by editing the `spec.kafka.version` field:

```bash
kubectl patch kafka railos-kafka -n railos \
  --type merge -p '{"spec":{"kafka":{"version":"3.8.0"}}}'
```

Strimzi performs a rolling restart broker-by-broker, maintaining availability throughout.
