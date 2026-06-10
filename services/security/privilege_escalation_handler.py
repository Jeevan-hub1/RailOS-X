"""
RailOS Privilege Escalation Alert Handler (Task 17.4)
Receives Falco JSON alerts, emits PRIVILEGE_ESCALATION_ALERT to Security_Officer,
logs event, and terminates the offending container within 30 seconds.
Satisfies: Req 39 C3–C4, Design §9.3
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from prometheus_client import Counter, start_http_server

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)

KAFKA_BOOTSTRAP   = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                    "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
ALERT_TOPIC       = "monitoring.alerts"
SECURITY_TOPIC    = "security.anomalies"
METRICS_PORT      = int(os.environ.get("METRICS_PORT", "8080"))
APP_PORT          = int(os.environ.get("APP_PORT", "8090"))
TERMINATE_TIMEOUT = float(os.environ.get("TERMINATE_TIMEOUT_SECONDS", "30"))
NAMESPACE         = os.environ.get("NAMESPACE", "railos")

escalation_counter = Counter(
    "privilege_escalation_alerts_total",
    "Total PRIVILEGE_ESCALATION_ALERT events handled",
)

app = FastAPI(title="RailOS Privilege Escalation Handler", docs_url=None)


@app.on_event("startup")
def _startup() -> None:
    start_http_server(METRICS_PORT)
    log.info("Privilege escalation handler started, listening on :%d", APP_PORT)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/falco/alert")
async def handle_falco_alert(request: Request) -> dict:
    """Receive a Falco JSON alert and process it (Task 17.4)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    rule     = body.get("rule", "")
    priority = body.get("priority", "").upper()
    output   = body.get("output", "")
    fields   = body.get("output_fields", {})

    # Only handle CRITICAL escalation rules
    if "PRIVILEGE_ESCALATION" not in rule.upper() and priority != "CRITICAL":
        return {"handled": False, "reason": "not a privilege escalation event"}

    container_name = (fields.get("container.name") or
                      _extract_field(output, "container=") or "unknown")
    pod_name       = (fields.get("k8s.pod.name") or
                      _extract_field(output, "pod=") or "unknown")
    capability     = (fields.get("syscall.type") or
                      _extract_field(output, "syscall=") or "unknown")

    alert_id = str(uuid.uuid4())
    event = {
        "alertId":       alert_id,
        "alertType":     "PRIVILEGE_ESCALATION_ALERT",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "containerName": container_name,
        "podName":       pod_name,
        "attemptedCapability": capability,
        "falcoRule":     rule,
        "rawOutput":     output,
        "namespace":     NAMESPACE,
    }

    log.critical("PRIVILEGE_ESCALATION_ALERT pod=%s container=%s capability=%s",
                 pod_name, container_name, capability)
    escalation_counter.inc()

    # 1. Emit alert to Security_Officer via Kafka
    _emit_alert(event)

    # 2. Schedule container termination within TERMINATE_TIMEOUT seconds
    t = threading.Thread(
        target=_terminate_container_after_delay,
        args=(pod_name, container_name, TERMINATE_TIMEOUT),
        daemon=True,
    )
    t.start()

    return {"handled": True, "alertId": alert_id, "terminationScheduled": True}


def _extract_field(output: str, prefix: str) -> str:
    """Extract a field value from Falco output string like 'field=value'."""
    try:
        start = output.index(prefix) + len(prefix)
        end   = output.find(" ", start)
        return output[start:end] if end > 0 else output[start:]
    except ValueError:
        return "unknown"


def _emit_alert(event: dict) -> None:
    """Publish PRIVILEGE_ESCALATION_ALERT to Kafka security and monitoring topics."""
    payload = json.dumps(event).encode()
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
        p.send(SECURITY_TOPIC, value=payload)
        p.send(ALERT_TOPIC, value=payload)
        p.flush(timeout=5)
        log.info("PRIVILEGE_ESCALATION_ALERT emitted to Kafka: alertId=%s", event["alertId"])
    except Exception as exc:
        log.error("Failed to emit alert to Kafka: %s", exc)


def _terminate_container_after_delay(pod_name: str, container_name: str, delay_s: float) -> None:
    """Delete the offending pod within TERMINATE_TIMEOUT seconds (Req 39 C3)."""
    log.info("Scheduling pod termination in %.0fs: pod=%s", delay_s, pod_name)
    time.sleep(max(0, delay_s - 5))  # Act 5s before deadline to ensure ≤30s

    if pod_name == "unknown":
        log.warning("Cannot terminate: pod name unknown")
        return

    start = time.monotonic()
    try:
        result = subprocess.run(
            ["kubectl", "delete", "pod", pod_name, "-n", NAMESPACE,
             "--grace-period=0", "--force"],
            capture_output=True, text=True, timeout=15,
        )
        elapsed = time.monotonic() - start
        if result.returncode == 0:
            log.info("Pod terminated in %.1fs: pod=%s", elapsed, pod_name)
        else:
            log.error("Pod termination failed: pod=%s stderr=%s", pod_name, result.stderr)
    except subprocess.TimeoutExpired:
        log.error("Pod termination command timed out after 15s: pod=%s", pod_name)
    except FileNotFoundError:
        log.warning("kubectl not found — cannot terminate pod (test environment)")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
