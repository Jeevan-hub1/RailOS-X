# RailOS Legacy System Adapters

Converts proprietary legacy system feeds (NTES, OMRS, WILD) into the RailOS
canonical sensor event schema and publishes them to Kafka.

**Requirement references:**
- **Req 1** — Sensor data ingestion from all active sensor feeds
- **Req 31** — Legacy system integration without modifying legacy systems

---

## Architecture

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │                    RailOS Adapter Layer                              │
  │                                                                     │
  │  ┌─────────────┐   HTTP/30s   ┌──────────────────────────────────┐  │
  │  │  NTES REST  │ ──────────── │                                  │  │
  │  │  API        │              │   shared/canonical_event.py      │  │
  │  └─────────────┘              │   (CanonicalEvent Pydantic model) │  │
  │                               │                                  │  │
  │  ┌─────────────┐   TCP/frames │   shared/dead_letter.py          │  │
  │  │  OMRS       │ ──────────── │   (DeadLetterRouter, Task 3.4)   │  │
  │  │  Stream     │              │                                  │  │
  │  └─────────────┘              │   shared/prometheus_metrics.py   │  │
  │                               │   (adapter_version label, 3.5)   │  │
  │  ┌─────────────┐   TCP/64B    │                                  │  │
  │  │  WILD       │ ──────────── └──────────────────────────────────┘  │
  │  │  Structs    │                           │                         │
  │  └─────────────┘                           │ publish                 │
  │                                            ▼                         │
  │                              ┌─────────────────────────┐            │
  │                              │        Kafka            │            │
  │                              │  train.telemetry.ntes   │            │
  │                              │  train.telemetry.omrs   │            │
  │                              │  train.telemetry.wild   │            │
  │                              │  monitoring.alerts      │            │
  │                              │  dead-letter.*          │            │
  │                              └─────────────────────────┘            │
  └─────────────────────────────────────────────────────────────────────┘

  Each adapter exposes Prometheus /metrics on :8080
  (adapter_events_total{adapter_name, adapter_version})
```

---

## Adapter Descriptions

| Adapter | Source        | Protocol       | Kafka Topic              | Sensor Type |
|---------|---------------|----------------|--------------------------|-------------|
| NTES    | NTES REST API | HTTP poll/30s  | `train.telemetry.ntes`   | `gps`       |
| OMRS    | OMRS Server   | TCP frames     | `train.telemetry.omrs`   | `wheel_load`|
| WILD    | WILD Sensor   | TCP 64B structs| `train.telemetry.wild`   | `wheel_load`|

---

## Dead-letter Routing (Req 1 / Task 3.4)

When any adapter encounters **3 consecutive parse failures** for the same
source ID, the shared `DeadLetterRouter`:

1. Publishes a `LEGACY_ADAPTER_FAILURE` alert to `monitoring.alerts`
2. Routes the raw payload bytes (hex-encoded) to `dead-letter.adapter-failures`
3. Resets the failure counter for that source

---

## Prometheus Metrics (Task 3.5)

Every adapter exposes three counters on `:8080/metrics`:

```
adapter_events_total{adapter_name="<name>", adapter_version="<version>"}
adapter_parse_failures_total{adapter_name="<name>"}
adapter_kafka_publish_errors_total{adapter_name="<name>"}
```

The `adapter_version` label enables per-version tracking of event throughput
and failure rates in Grafana/Prometheus.

---

## Deployment Instructions

### Kubernetes (production)

```bash
# Apply namespace-level resources first (if not already present)
kubectl apply -f infra/k8s-security/01-namespace-policies.yaml

# Deploy each adapter
kubectl apply -f services/adapters/ntes/01-configmap.yaml
kubectl apply -f services/adapters/ntes/02-deployment.yaml

kubectl apply -f services/adapters/omrs/01-configmap.yaml
kubectl apply -f services/adapters/omrs/02-deployment.yaml

kubectl apply -f services/adapters/wild/01-configmap.yaml
kubectl apply -f services/adapters/wild/02-deployment.yaml
```

Each deployment:
- Runs as UID/GID 1000 (non-root)
- Drops all Linux capabilities
- Has `allowPrivilegeEscalation: false` and `readOnlyRootFilesystem: true`
- Carries `prometheus.io/scrape: "true"` annotations for auto-discovery

### Local Development (docker-compose)

```bash
cd services/adapters
docker-compose up --build
```

This starts a local Kafka broker and all three adapters.  Point your mock
legacy servers at the ports configured in `docker-compose.yml`:

| Service | Metrics port |
|---------|-------------|
| NTES    | localhost:8081/metrics |
| OMRS    | localhost:8082/metrics |
| WILD    | localhost:8083/metrics |
| Kafka   | localhost:9092 |

---

## Running Tests

```bash
cd services/adapters
pip install pydantic==2.7.0 prometheus-client==0.20.0 pytest
pytest tests/ -v
```

No Kafka broker or live legacy systems are required — all external I/O is
replaced by mock fixtures.

---

## How to Add a New Adapter

1. **Create `services/adapters/<name>/`**

2. **Implement `<name>_adapter.py`**:
   - Import `CanonicalEvent`, `QualityFlags` from `shared.canonical_event`
   - Import `DeadLetterRouter` from `shared.dead_letter`
   - Import `make_metrics`, `start_metrics_server` from `shared.prometheus_metrics`
   - Write a `parse_<name>_<record>()` function that returns a `CanonicalEvent`
   - Call `router.record_failure()` on parse errors; `router.reset()` on success
   - Call `metrics.events_total.inc()` / `metrics.parse_failures_total.inc()`
   - Choose a `sensorType` from the allowed set:
     `vibration | temperature | gps | wheel_load | acoustic | camera`

3. **Add `requirements.txt`** (pin `kafka-python==2.0.2`, `prometheus-client==0.20.0`,
   `pydantic==2.7.0` plus any adapter-specific deps)

4. **Add `Dockerfile`**: copy from `ntes/Dockerfile`, update paths and CMD

5. **Add `01-configmap.yaml`** with the new adapter's connection env vars and
   `ADAPTER_VERSION`

6. **Add `02-deployment.yaml`**: copy from an existing adapter, set
   `adapter_version` label, `prometheus.io/scrape` annotation, non-root UID

7. **Add a service entry to `docker-compose.yml`** for local testing

8. **Write unit tests in `tests/test_<name>_adapter.py`**:
   - Valid record → correct `CanonicalEvent` fields
   - 3 failures → `LEGACY_ADAPTER_FAILURE` alert + dead-letter published
   - Kafka message JSON matches canonical schema

9. **Add test fixtures to `tests/conftest.py`**

10. **Update this README** with the new adapter in the table above
