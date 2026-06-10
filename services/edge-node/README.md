# RailOS Edge Node

Tier-2 edge agent running on Jetson Orin NX/AGX hardware at each station.
Provides local ML inference, 24-hour event buffering, autonomous operation
during network partitions, and Prometheus telemetry.

**Requirement references**: Req 2 (autonomous operation), Req 33 (network partition handling), Req 44 (hardware telemetry)

---

## FSM State Diagram

```
                  3 failures / 30s window
  ┌─────────────┐ ───────────────────────► ┌───────────────┐
  │  CONNECTED  │                          │  AUTONOMOUS   │
  └─────────────┘ ◄─────────────────────── └───────────────┘
        ▲           record_upload_complete        │
        │                                         │ first heartbeat success
        │         ┌───────────────────┐           │
        └──────── │   RECONNECTING    │ ◄─────────┘
                  └───────────────────┘
                    upload_buffered_events()
                    → record_upload_complete()
                    → transitions to CONNECTED

  States
  ------
  CONNECTED    Normal operation. Heartbeats succeed.
               Metric gauge value: 0

  AUTONOMOUS   Network partition detected. Local ML inference continues.
               Events written to CircularBuffer (SQLite, 24h NVMe-backed).
               Metric gauge value: 1

  RECONNECTING First successful heartbeat after partition.
               Uploads buffered events to Data_Pipeline before resuming.
               Metric gauge value: 2
```

---

## Module Map

| Module | File | Purpose | Requirement |
|--------|------|---------|-------------|
| Heartbeat FSM | `heartbeat/heartbeat_fsm.py` | 3-state FSM: CONNECTED → AUTONOMOUS → RECONNECTING | Req 2 C1, Req 33 C1 |
| Circular Buffer | `buffer/circular_buffer.py` | SQLite-backed 24h event buffer; overwrites oldest on full | Req 2 C2 |
| Reconnect Uploader | `uploader/reconnect_uploader.py` | Timestamp-ordered upload with per-record ACK and 3 retries | Req 2 C3 |
| Model Store | `model_store/model_store.py` | NVMe-backed model weight store; cold-restart capable | Req 2 C4 |
| Storage Alerter | `alerter/storage_alerter.py` | Monitors buffer capacity; SMS → console → audit log at ≥90% | Req 2 C5 |
| Main Agent | `main.py` | Ties all modules together; starts threads; exposes metrics | Req 2, Req 33, Req 44 |

---

## Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `edge_node_state` | Gauge | — | Current FSM state: 0=CONNECTED, 1=AUTONOMOUS, 2=RECONNECTING |
| `edge_upload_events_total` | Counter | — | Total events successfully uploaded on reconnect |
| `edge_upload_failures_total` | Counter | — | Total events that failed all upload retries |

Metrics are exposed on port **8080** at `/metrics` (Prometheus text format).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PIPELINE_URL` | `http://data-pipeline.railos.svc.cluster.local:8080` | Central Data_Pipeline base URL |
| `BUFFER_DB_PATH` | `/data/buffer/events.db` | SQLite circular buffer path |
| `MODEL_STORE_PATH` | `/data/models` | NVMe model weight store root |
| `SMS_GATEWAY_URL` | _(empty)_ | SMS gateway URL for storage alerts |
| `METRICS_PORT` | `8080` | Prometheus HTTP metrics port |
| `ALERT_LOG_PATH` | `/data/logs/storage_alerts.jsonl` | Audit log for storage threshold alerts |
| `HEARTBEAT_INTERVAL_S` | `10` | Seconds between pipeline heartbeat POSTs |
| `CHECK_INTERVAL_SECONDS` | `60` | Seconds between storage capacity checks |
| `CAPACITY_THRESHOLD_PCT` | `90` | Buffer fill % that triggers alert |

---

## Deployment Instructions

### Prerequisites

- Kubernetes cluster with `railos` namespace
- Nodes running Jetson Orin NX/AGX hardware labelled with `railos.io/role=edge-node`
- `edge-node-secrets` Secret with keys: `PIPELINE_URL`, `SMS_GATEWAY_URL`
- Host directory `/data/railos` writable by UID 1000

### 1. Build the container image

```bash
# from repository root
docker build \
  -t railos/edge-node:latest \
  services/edge-node/
```

For ARM64 Jetson targets:

```bash
docker buildx build \
  --platform linux/arm64 \
  -t railos/edge-node:latest \
  services/edge-node/
```

### 2. Push the image

```bash
docker push railos/edge-node:latest
```

### 3. Create the secrets

```bash
kubectl -n railos create secret generic edge-node-secrets \
  --from-literal=PIPELINE_URL=http://data-pipeline.railos.svc.cluster.local:8080 \
  --from-literal=SMS_GATEWAY_URL=https://sms-gw.railos.internal/send
```

### 4. Deploy the DaemonSet

```bash
kubectl apply -f services/edge-node/k8s/01-daemonset.yaml
```

### 5. Verify

```bash
# Check pods are running on edge nodes
kubectl -n railos get pods -l app=railos-edge-node -o wide

# Confirm Prometheus metrics are reachable
kubectl -n railos port-forward daemonset/railos-edge-node 8080:8080
curl http://localhost:8080/metrics | grep edge_node_state
```

### 6. Upgrade (rolling)

The DaemonSet uses `RollingUpdate` with `maxUnavailable: 1`, so updates
roll out one node at a time without service interruption:

```bash
kubectl -n railos set image daemonset/railos-edge-node \
  edge-node=railos/edge-node:<new-tag>
```

---

## Running Tests

```bash
# From repository root
pip install pytest httpx prometheus-client

cd services/edge-node
python -m pytest tests/ -v
```

---

## Requirement References

| Requirement | Summary | Coverage |
|-------------|---------|----------|
| **Req 2** | Autonomous edge operation: local inference continues during connectivity loss | `heartbeat_fsm.py`, `main.py`, `circular_buffer.py`, `model_store.py` |
| **Req 33** | Network partition handling: 3 failures → AUTONOMOUS, reconnect → ordered upload | `heartbeat_fsm.py`, `reconnect_uploader.py` |
| **Req 44** | Hardware telemetry: Prometheus metrics for FSM state and upload counters | `main.py` (Gauge `edge_node_state`), `reconnect_uploader.py` (Counters) |
