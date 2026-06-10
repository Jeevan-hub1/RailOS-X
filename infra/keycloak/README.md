# Keycloak Identity Provider

Keycloak 24 deployment for the RailOS Pilot System. Provides RS256 JWT-based authentication,
TOTP MFA enforcement, and RBAC for all four operator roles. Kong API Gateway validates JWTs
issued by this instance via the JWKS endpoint.

---

## Contents

| File | Purpose |
|------|---------|
| `01-secrets.yaml` | Admin credentials + DB password (placeholders — replace before deploy) |
| `02-configmap.yaml` | Realm export JSON (`railos` realm, 4 roles, TOTP policy, RS256, `railos-api` client) |
| `03-services.yaml` | ClusterIP service on port 8080 + headless service for StatefulSet DNS |
| `04-statefulset.yaml` | Keycloak 24.0 StatefulSet (1 replica, non-root, PostgreSQL backend, realm import) |
| `05-prometheus-rules.yaml` | PrometheusRules: pod up/down, login failure rate, TOTP removal, token latency |

---

## Prerequisites

1. The `railos` namespace must exist (`kubectl apply -f infra/kafka/namespace.yaml`).
2. The Patroni PostgreSQL cluster must be running (`infra/postgresql/`).
3. Create the `keycloak` database in PostgreSQL before first deploy:
   ```bash
   kubectl exec -n railos -it postgresql-0 -- \
     psql -U postgres -c "CREATE DATABASE keycloak OWNER keycloak_user;"
   ```
   Replace `keycloak_user` with the value set in `01-secrets.yaml` `db-user`.
4. Prometheus Operator must be installed for `05-prometheus-rules.yaml` to take effect.

---

## Replacing placeholder secrets

All `data` values in `01-secrets.yaml` are base64-encoded placeholders. Replace them before
applying:

```bash
# Generate a value
echo -n 'your-strong-password-here' | base64

# Patch in-place (or edit 01-secrets.yaml and re-apply)
kubectl create secret generic keycloak-admin-secret \
  --namespace railos \
  --from-literal=admin-user='kc-admin' \
  --from-literal=admin-password='<strong-random-password>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic keycloak-db-secret \
  --namespace railos \
  --from-literal=db-user='keycloak' \
  --from-literal=db-password='<strong-random-password>' \
  --dry-run=client -o yaml | kubectl apply -f -
```

For production, use the **External Secrets Operator** pointed at HashiCorp Vault
(Design §9.1, Req 37) instead of managing secrets in YAML files.

---

## Deployment

Apply manifests in order:

```bash
kubectl apply -f infra/keycloak/01-secrets.yaml
kubectl apply -f infra/keycloak/02-configmap.yaml
kubectl apply -f infra/keycloak/03-services.yaml
kubectl apply -f infra/keycloak/04-statefulset.yaml
kubectl apply -f infra/keycloak/05-prometheus-rules.yaml
```

Wait for Keycloak to become ready (realm import + DB init can take 2–4 minutes on first boot):

```bash
kubectl rollout status statefulset/keycloak -n railos --timeout=300s
```

Verify the realm was imported:

```bash
# Port-forward the Keycloak management port
kubectl port-forward -n railos svc/keycloak 8080:8080 &

# Check realm exists
curl -s http://localhost:8080/realms/railos/.well-known/openid-configuration | jq .issuer
# Expected: "http://localhost:8080/realms/railos"

# Verify JWKS endpoint (Kong uses this for RS256 key fetching)
curl -s http://localhost:8080/realms/railos/protocol/openid-connect/certs | jq .keys[].alg
# Expected: "RS256"
```

---

## TOTP MFA Setup

TOTP enforcement is configured in the realm JSON (`02-configmap.yaml`) as a **default required action**.
Every new account in the `railos` realm will be prompted to configure TOTP on first login.

### For administrators — enrolling a privileged user

1. Create the user in Keycloak Admin Console → Realm: `railos` → Users → Add user.
2. Assign the appropriate realm role (`Operations_Controller`, `Security_Officer`,
   `Engineering_Team`, or `Governance_Officer`).
3. Set a temporary password under the **Credentials** tab and enable **Temporary** toggle.
4. On first login the user will be required to:
   - Set a permanent password
   - Configure TOTP (scan QR code with any RFC 6238-compatible authenticator app)

### Supported authenticator apps

The realm is configured to support:
- **FreeOTP** (Red Hat, open source)
- **Google Authenticator**
- **Microsoft Authenticator**

Any RFC 6238 TOTP app (HmacSHA1, 6 digits, 30-second period) will work.

### Verifying TOTP is active

```bash
# List users in realm (requires admin token)
ADMIN_TOKEN=$(curl -s -X POST \
  http://localhost:8080/realms/master/protocol/openid-connect/token \
  -d "client_id=admin-cli&grant_type=password&username=<admin>&password=<pass>" \
  | jq -r .access_token)

# Check configured credentials for a user
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8080/admin/realms/railos/users?username=<target-user> | jq .[0].id

# Then check credentials
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8080/admin/realms/railos/users/<user-id>/credentials | jq .[].type
# Expected: includes "otp"
```

---

## RBAC Roles

Four realm roles are defined in the `railos` realm:

| Role | Permissions |
|------|------------|
| `Operations_Controller` | View and authorize advisories; human-in-the-loop authorization gate (Req 12) |
| `Security_Officer` | Acknowledge security anomalies; view audit logs; place/release forensic holds (Req 9, Req 26) |
| `Engineering_Team` | Deploy/rollback ML models; configure drift thresholds; view audit logs (Req 11) |
| `Governance_Officer` | Request data lineage reports; configure retention policies; place/release forensic holds (Req 13, Req 28) |

Roles are enforced via Keycloak Authorization Services on the `railos-api` client.
Kong API Gateway injects the Bearer JWT; downstream services inspect the `realm_access.roles`
claim or use the Keycloak token introspection endpoint.

---

## Kong API Gateway Integration (Design §9.2)

Configure the Kong JWT plugin to validate RS256 tokens from this Keycloak instance:

```yaml
# Kong plugin configuration (declarative / deck format)
plugins:
  - name: jwt
    config:
      key_claim_name: kid
      claims_to_verify:
        - exp
        - nbf
      # Keycloak JWKS endpoint — Kong resolves RS256 public keys from here
      # URL: http://keycloak.railos.svc.cluster.local:8080/realms/railos/protocol/openid-connect/certs
      # Configure via Kong JWKS plugin or manually add RSA public key as a Consumer credential
      secret_is_base64: false
      run_on_preflight: true
```

For production, use the **Kong OpenID Connect plugin** (Kong EE) or the open-source
**lua-resty-openidc** library, pointing the issuer to:
```
http://keycloak.railos.svc.cluster.local:8080/realms/railos
```

---

## Observability

PrometheusRules (`05-prometheus-rules.yaml`) fire alerts for:

| Alert | Condition | Severity |
|-------|-----------|----------|
| `KeycloakDown` | Pod not ready for > 1 min | critical |
| `KeycloakMetricsEndpointDown` | Scrape failing for > 2 min | warning |
| `KeycloakLoginFailureRateHigh` | > 10 failures/min for 2 min | warning |
| `KeycloakLoginFailureRateCritical` | > 50 failures/min for 1 min | critical |
| `KeycloakAccountLockoutRateHigh` | > 2 lockouts/min for 5 min | warning |
| `KeycloakTOTPRemovedFromAccount` | Any TOTP removal in last 1h | warning |
| `KeycloakTokenEndpointLatencyHigh` | P95 token endpoint > 1s for 5 min | warning |
| `KeycloakJWKSEndpointLatencyHigh` | P95 JWKS endpoint > 500ms for 5 min | warning |

Metrics are scraped from the management port (`9000/metrics`) when `--metrics-enabled=true`
is set (included in the StatefulSet args).

---

## Scaling

The StatefulSet is configured with `replicas: 1` (pilot system). To scale to 2+ replicas:

1. Increment `replicas` in `04-statefulset.yaml`.
2. Ensure the headless service (`keycloak-headless`) is in place — JGroups DNS_PING
   uses it for cluster member discovery.
3. Keycloak 24 uses Infinispan distributed cache with `--cache=ispn --cache-stack=kubernetes`
   (already set). No additional configuration is required for active-active clustering.

---

## Troubleshooting

```bash
# View Keycloak startup logs (realm import progress)
kubectl logs -n railos keycloak-0 -f

# Check if realm import completed
kubectl logs -n railos keycloak-0 | grep -i "import"

# Describe the pod for events / init container status
kubectl describe pod keycloak-0 -n railos

# Test DB connectivity from inside the pod
kubectl exec -n railos keycloak-0 -- \
  sh -c 'nc -zv postgresql-primary.railos.svc.cluster.local 5432 && echo OK'

# Check Prometheus metrics are exposed
kubectl exec -n railos keycloak-0 -- \
  curl -s http://localhost:9000/metrics | grep keycloak_event
```
