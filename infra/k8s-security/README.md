# RailOS Kubernetes Security Hardening

Implements Design §9.3 / Req 39 cluster-level security controls.

## Files

| File | Purpose |
|------|---------|
| `01-namespace-policies.yaml` | Pod Security Admission labels on all RailOS namespaces |
| `02-network-policies.yaml` | Default-deny + allow-list NetworkPolicies |
| `03-rbac.yaml` | RBAC for Vault SA, Falco SA, and service reader roles |

## Pod Security Admission

Three namespaces with different trust levels:

| Namespace | PSA Profile | Used By |
|-----------|-------------|---------|
| `railos` | **restricted** | All application services |
| `railos-system` | **privileged** | Falco, linuxptp DaemonSets (require NET_ADMIN) |
| `railos-monitoring` | **baseline** | Prometheus, Grafana, Jaeger |

Restricted profile enforces: `runAsNonRoot`, `allowPrivilegeEscalation=false`, `capabilities drop ALL`, `seccompProfile=RuntimeDefault`.

## Network Policies

Default-deny is applied first, then explicit allow-lists open only required paths:

- DNS (UDP/TCP 53) — all pods
- Kafka (9092/9093) — all pods → kafka pods
- InfluxDB (8086) — all pods → influxdb pods
- PostgreSQL (5432) — all pods → postgresql + postgis pods
- MinIO (9000) — all pods → minio pods
- Vault (8200) — all pods → vault pods
- Keycloak (8080/9000) — kong → keycloak
- Prometheus scrape — railos-monitoring → all pods on metrics ports
- Flink internal — flink → flink (6122-6124/8081)

## Deployment

```bash
kubectl apply -f infra/k8s-security/01-namespace-policies.yaml
kubectl apply -f infra/k8s-security/02-network-policies.yaml
kubectl apply -f infra/k8s-security/03-rbac.yaml
```

Apply namespace policies before deploying any pods to ensure PSA is active from the start.
