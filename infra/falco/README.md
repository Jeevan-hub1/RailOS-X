# RailOS Falco Runtime Security (Tasks 17.3–17.4)

Detects and responds to privilege escalation attempts in RailOS containers.

**Satisfies:** Req 39 C3–C4, Design §9.3

---

## Files

| File | Purpose |
|------|---------|
| `01-configmap.yaml` | Falco rules: privilege escalation via setuid/setgid, unexpected capabilities, read-only FS violations |
| `02-daemonset.yaml` | Falco DaemonSet (railos-system namespace, privileged) + RBAC |
| `03-handler-deployment.yaml` | Falco alert handler: receives JSON alerts → Kafka + pod termination |

---

## How It Works

```
Falco DaemonSet (railos-system)
  └── Monitors kernel syscalls on all nodes
  └── Fires CRITICAL alert on privilege escalation attempt
  └── Sends JSON alert to falco-alert-handler:8090/falco/alert

falco-alert-handler (railos namespace)
  ├── Emits PRIVILEGE_ESCALATION_ALERT to security.anomalies + monitoring.alerts Kafka topics
  ├── Logs: container name, pod name, attempted capability, timestamp
  └── Terminates offending pod via kubectl delete within 30 seconds
```

---

## Deployment

```bash
# 1. Create railos-system namespace if not exists
kubectl create namespace railos-system 2>/dev/null || true

# 2. Apply Falco rules ConfigMap to railos namespace
kubectl apply -f infra/falco/01-configmap.yaml -n railos

# 3. Deploy Falco DaemonSet to railos-system (privileged)
kubectl apply -f infra/falco/02-daemonset.yaml

# 4. Build and push handler image
docker build -t railos/falco-alert-handler:1.0.0 services/security/
docker push your-registry/railos/falco-alert-handler:1.0.0

# 5. Deploy handler (update image in 03-handler-deployment.yaml first)
kubectl apply -f infra/falco/03-handler-deployment.yaml -n railos

# 6. Verify Falco is running on all nodes
kubectl get pods -n railos-system -l app=falco
```

---

## Testing

Send a synthetic Falco CRITICAL alert to the handler:

```bash
kubectl port-forward -n railos svc/falco-alert-handler 8090:8090 &

curl -s -X POST http://localhost:8090/falco/alert \
  -H "Content-Type: application/json" \
  -d '{
    "rule": "RailOS Privilege Escalation via setuid/setgid",
    "priority": "CRITICAL",
    "output": "PRIVILEGE_ESCALATION_ALERT container=defect-detector pod=defect-detector-abc123 syscall=setuid",
    "output_fields": {
      "container.name": "defect-detector",
      "k8s.pod.name": "defect-detector-abc123",
      "syscall.type": "setuid"
    }
  }'
```

Expected: PRIVILEGE_ESCALATION_ALERT in `security.anomalies` Kafka topic within 1 second.
Expected: Pod deletion attempt within 30 seconds.
