# RailOS Kong API Gateway 3.6 — Deployment Guide

This directory contains Kubernetes manifests to deploy Kong API Gateway (DB-less mode)
as the single ingress point for all RailOS Pilot REST APIs.

## Configuration Summary

| Parameter | Value |
|-----------|-------|
| Kong version | 3.6 |
| Mode | DB-less (declarative config) |
| Replicas | 2 (zero-downtime rolling updates) |
| Proxy port | 8000 (HTTP), 8443 (HTTPS) |
| Admin API port | 8001 (HTTP), 8444 (HTTPS) |
| Namespace | `railos` |
| JWT algorithm | RS256 |
| JWKS endpoint | `http://keycloak.railos.svc.cluster.local:8080/realms/railos/protocol/openid-connect/certs` |
| OIDC issuer | `http://keycloak.railos.svc.cluster.local:8080/realms/railos` |
| Rate limit | 1,000 req/min per consumer (HTTP 429 + Retry-After) |
| Versioned routing prefix | `/api/v1/*` (current); `/api/v2/*` reserved for breaking changes |
| Trace header | `X-Trace-ID` injected from OpenTelemetry span (via request-transformer plugin) |

These settings satisfy **Design §9.2** (Kong configuration), **Requirement 24** (API gateway
for all RailOS REST endpoints), and **Requirement 39** (non-root container security).

---

## Directory Layout

```
infra/kong/
├── README.md                  # This file
├── 01-configmap.yaml          # Kong declarative config (kong.yml): jwt, rate-limiting,
│                              #   request-transformer, opentelemetry, prometheus plugins;
│                              #   versioned routes for all RailOS services
├── 02-secrets.yaml            # Admin JWT secret + Keycloak JWKS URI (placeholders)
├── 03-services.yaml           # ClusterIP services: kong-proxy (:8000) and kong-admin (:8001)
├── 04-deployment.yaml         # Kong 3.6 Deployment: 2 replicas, non-root, DB-less mode
└── 05-prometheus-rules.yaml   # PrometheusRule: request rates, rate-limit hits, latency P95
```

---

## Architecture

```
                ┌──────────────────────────────────────────────────────┐
                │  Kubernetes Cluster — namespace: railos               │
                │                                                        │
 Browser /      │  ┌──────────────────────────────────────────────────┐ │
 Operator UI ──►│  │  kong-proxy Service (ClusterIP :8000)            │ │
                │  └──────────────────┬───────────────────────────────┘ │
                │                     │                                  │
                │  ┌──────────────────▼───────────────────────────────┐ │
                │  │  Kong Pod (replica 1 or 2)                        │ │
                │  │  ┌────────────────────────────────────────────┐  │ │
                │  │  │  Plugins (global):                          │  │ │
                │  │  │   1. jwt (RS256) → validate Keycloak token  │  │ │
                │  │  │   2. rate-limiting → 1,000 req/min/consumer │  │ │
                │  │  │   3. request-transformer → X-Trace-ID       │  │ │
                │  │  │   4. opentelemetry → Jaeger trace context   │  │ │
                │  │  │   5. prometheus → metrics at :8001/metrics  │  │ │
                │  │  └────────────────────────────────────────────┘  │ │
                │  │                                                    │ │
                │  │  Routes:                                           │ │
                │  │   /api/v1/delay-predictor  → delay-predictor:8080 │ │
                │  │   /api/v1/digital-twin     → digital-twin:3000    │ │
                │  │   /api/v1/scheduler        → marl-scheduler:8080  │ │
                │  │   /api/v1/defect-detector  → defect-detector:8080 │ │
                │  │   /api/v1/maintenance      → maintenance-engine:8080│ │
                │  │   /api/v1/mlflow           → mlflow:5000          │ │
                │  │   /api/v1/security         → security-dashboard:3000│ │
                │  │   /api/v2/*                → HTTP 501 (stub)      │ │
                │  └────────────────────────────────────────────────────┘ │
                │                                                        │
                │  Keycloak ──► JWKS (RS256 public keys)                │
                │  Jaeger   ──► Trace collector                         │
                │  Prometheus ◄── :8001/metrics                         │
                └──────────────────────────────────────────────────────┘
```

---

## Prerequisites

- Kubernetes 1.25+ cluster
- `railos` namespace (deploy `infra/kafka/namespace.yaml` first)
- Prometheus Operator installed (for `PrometheusRule` CRD)
- Keycloak deployed and reachable at `keycloak.railos.svc.cluster.local:8080`
- Jaeger Collector reachable at `jaeger-collector.railos.svc.cluster.local:4318`

---

## Deployment

### 1. Replace placeholder secrets

Edit `02-secrets.yaml` and replace all `REPLACE_WITH_*` values:

```bash
ADMIN_SECRET=$(openssl rand -hex 32)
CONFIG_SECRET=$(openssl rand -hex 32)

# Or use kubectl directly
kubectl create secret generic kong-auth \
  --namespace railos \
  --from-literal=KONG_ADMIN_JWT_SECRET="${ADMIN_SECRET}" \
  --from-literal=KONG_DECLARATIVE_CONFIG_SECRET="${CONFIG_SECRET}" \
  --from-literal=KEYCLOAK_JWKS_URI="http://keycloak.railos.svc.cluster.local:8080/realms/railos/protocol/openid-connect/certs" \
  --from-literal=OIDC_ISSUER="http://keycloak.railos.svc.cluster.local:8080/realms/railos"
```

**Production note:** Populate secrets via HashiCorp Vault Agent Injector or External Secrets
Operator pointing at `secret/railos/kong/*` in Vault. Do not commit credentials to source control.

### 2. Apply manifests in order

```bash
kubectl apply -f infra/kong/01-configmap.yaml
kubectl apply -f infra/kong/02-secrets.yaml     # skip if using Vault
kubectl apply -f infra/kong/03-services.yaml
kubectl apply -f infra/kong/04-deployment.yaml

# Wait for rollout
kubectl rollout status deployment/kong -n railos --timeout=3m

# Prometheus rules (requires Prometheus Operator)
kubectl apply -f infra/kong/05-prometheus-rules.yaml
```

### 3. Verify deployment

```bash
# Check pods
kubectl get pods -n railos -l app=kong

# Check Admin API health
kubectl exec -n railos deploy/kong -- curl -sf http://localhost:8001/status | python3 -m json.tool

# Check loaded routes
kubectl exec -n railos deploy/kong -- curl -sf http://localhost:8001/routes | python3 -m json.tool

# Check plugins
kubectl exec -n railos deploy/kong -- curl -sf http://localhost:8001/plugins | python3 -m json.tool

# Test JWT validation (should return 401 without token)
kubectl exec -n railos deploy/kong -- \
  curl -sf -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/delay-predictor/health
# Expected: 401

# Test rate limiting (send 1001 requests quickly to observe 429)
# Test with a valid Keycloak JWT for your test consumer
```

---

## JWT Configuration

Kong's `jwt` plugin validates RS256 JWTs issued by Keycloak. The public key is retrieved
from the Keycloak JWKS endpoint automatically at startup.

**To register a consumer's JWT credential** (declarative config approach):

Add to `kong.yml` consumers section:

```yaml
consumers:
  - username: my-service
    jwt_secrets:
      - algorithm: RS256
        rsa_public_key: |
          -----BEGIN PUBLIC KEY-----
          <paste Keycloak RS256 public key here>
          -----END PUBLIC KEY-----
        key: "http://keycloak.railos.svc.cluster.local:8080/realms/railos"
```

The `key` field must match the `iss` claim in the JWT. Kong will then look up the
consumer by `kid` header in the JWT and validate the signature.

---

## Versioned Routing

All current RailOS services are exposed under `/api/v1/`. When a breaking API change
is required for any service, the process is:

1. Deploy the new service version with a different internal name
2. Add a new `/api/v2/<service>` route in `kong.yml` pointing at the new service
3. Keep `/api/v1/<service>` running during the migration period
4. Deprecate and remove v1 only after all clients have migrated

The `/api/v2/*` stub currently returns HTTP 501 to prevent accidental usage before
v2 services are ready.

---

## Rate Limiting Notes

The current configuration uses `policy: local` (in-memory per-pod counter). With 2 replicas,
each pod enforces 1,000 req/min independently, meaning a single consumer could make up to
2,000 req/min total before hitting limits.

**For production** with strict per-client enforcement across replicas, switch to Redis:

1. Deploy a Redis instance in the `railos` namespace
2. In `01-configmap.yaml`, change the rate-limiting plugin config:
   ```yaml
   policy: redis
   redis_host: redis.railos.svc.cluster.local
   redis_port: 6379
   redis_database: 0
   ```
3. Apply the updated ConfigMap and restart Kong pods

---

## Requirement Traceability

| Manifest | Requirement | Criterion |
|----------|-------------|-----------|
| `01-configmap.yaml` | Design §9.2 | JWT plugin, rate-limiting, request-transformer, versioned routing |
| `01-configmap.yaml` | Req 24 | API gateway for all RailOS REST endpoints |
| `04-deployment.yaml` | Req 39 | Non-root, no privilege escalation, capabilities drop ALL |
| `05-prometheus-rules.yaml` | Req 17 | Prometheus metrics for Kong |
| `05-prometheus-rules.yaml` | Req 25 | Latency P95 monitoring for e2e SLA |
