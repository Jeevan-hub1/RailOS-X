"""
RailOS Human-in-the-Loop Authorization Gate (Tasks 14.1–14.8)
Structural boundary: no advisory reaches any operational system without OC authorization.
Satisfies: Req 12, Req 30, Req 40, Design §12
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, start_http_server
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)

KAFKA_BOOTSTRAP   = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                    "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
DB_URL            = os.environ.get("DB_URL",
                                    "postgresql://railos:change-me@postgresql-primary.railos.svc.cluster.local:5432/railos")
METRICS_PORT      = int(os.environ.get("METRICS_PORT", "8080"))
APP_PORT          = int(os.environ.get("APP_PORT", "8086"))
ESCALATION_TIMEOUT_S  = float(os.environ.get("ESCALATION_TIMEOUT_SECONDS", "600"))  # 10 min

# Prometheus
gate_status_gauge     = Gauge("railos_authorization_gate_status",
                               "0=unavailable, 1=degraded, 2=operational")
advisories_authorized = Counter("advisories_authorized_total", "Advisories authorized")
advisories_rejected   = Counter("advisories_rejected_total",   "Advisories rejected")
tier1_dual_auth       = Counter("tier1_dual_auth_completions_total", "Tier 1 dual-auth completions")

# ── Risk scoring ──────────────────────────────────────────────────────────────
SEVERITY_WEIGHTS = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


def compute_risk_score(probability: float, severity: str) -> float:
    """risk_score = probability × severity_weight, capped at 4.0 (Req 40 C1)."""
    w = SEVERITY_WEIGHTS.get(severity.upper(), 1)
    return min(4.0, max(0.0, probability * w))


def risk_tier(score: float) -> int:
    """Tier 1 ≥3.2 (dual-auth), Tier 2 2.0–3.19, Tier 3 <2.0 (Req 40 C2)."""
    if score >= 3.2:
        return 1
    if score >= 2.0:
        return 2
    return 3


# ── Advisory queue ────────────────────────────────────────────────────────────
class _QueuedAdvisory:
    def __init__(self, advisory_id: str, payload: dict, score: float, tier: int) -> None:
        self.advisory_id      = advisory_id
        self.payload          = payload
        self.risk_score       = score
        self.risk_tier        = tier
        self.created_at       = time.monotonic()
        self.first_auth_by:   Optional[str] = None
        self.escalated        = False


_queue:    dict[str, _QueuedAdvisory] = {}
_queue_lock = threading.Lock()
_gate_operational = True


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="RailOS Authorization Gate", docs_url=None, redoc_url=None)


class AuthorizeRequest(BaseModel):
    advisoryId:   str
    controllerId: str
    action:       str  # AUTHORIZE | REJECT


class EnqueueRequest(BaseModel):
    advisoryId: str
    payload:    dict
    probability: float = 0.5
    severity:    str   = "HIGH"


@app.on_event("startup")
def _startup() -> None:
    start_http_server(METRICS_PORT)
    gate_status_gauge.set(2)  # operational
    # Start escalation checker thread
    t = threading.Thread(target=_escalation_loop, daemon=True)
    t.start()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "gate": "operational" if _gate_operational else "unavailable"}


@app.post("/api/v1/gate/enqueue")
def enqueue_advisory(req: EnqueueRequest) -> dict:
    """Receive an advisory from ML subsystems; add to authorization queue."""
    score = compute_risk_score(req.probability, req.severity)
    tier  = risk_tier(score)
    qa    = _QueuedAdvisory(req.advisoryId, req.payload, score, tier)
    with _queue_lock:
        _queue[req.advisoryId] = qa
    log.info("Advisory enqueued id=%s score=%.2f tier=%d", req.advisoryId, score, tier)
    return {"advisoryId": req.advisoryId, "riskScore": score, "riskTier": tier}


@app.post("/api/v1/gate/authorize")
def authorize(req: AuthorizeRequest) -> dict:
    """Process Authorize or Reject action from Operations_Controller."""
    global _gate_operational
    if not _gate_operational:
        raise HTTPException(503, detail="Authorization gate is unavailable — advisory queued")

    with _queue_lock:
        qa = _queue.get(req.advisoryId)
        if qa is None:
            raise HTTPException(404, detail="Advisory not found in queue")

        if req.action.upper() == "AUTHORIZE":
            if qa.risk_tier == 1:
                # Tier 1: requires two distinct controller IDs (Req 40 C3)
                if qa.first_auth_by is None:
                    qa.first_auth_by = req.controllerId
                    return {"status": "AWAITING_SECOND_AUTH", "firstAuthBy": req.controllerId}
                if qa.first_auth_by == req.controllerId:
                    raise HTTPException(400, detail="Second authorization must be from a different controller")
                # Both authorized — forward
                _forward_advisory(qa, req.controllerId)
                del _queue[req.advisoryId]
                tier1_dual_auth.inc()
            else:
                _forward_advisory(qa, req.controllerId)
                del _queue[req.advisoryId]
            advisories_authorized.inc()
            _write_audit_log(req.advisoryId, "AUTHORIZE", req.controllerId, qa)
            return {"status": "AUTHORIZED", "advisoryId": req.advisoryId}

        elif req.action.upper() == "REJECT":
            del _queue[req.advisoryId]
            advisories_rejected.inc()
            _write_audit_log(req.advisoryId, "REJECT", req.controllerId, qa)
            return {"status": "REJECTED", "advisoryId": req.advisoryId}

        raise HTTPException(400, detail="action must be AUTHORIZE or REJECT")


@app.get("/api/v1/gate/queue")
def get_queue() -> dict:
    """Return current advisory queue sorted by risk score descending."""
    with _queue_lock:
        items = sorted(_queue.values(), key=lambda q: -q.risk_score)
        return {"advisories": [
            {"advisoryId": q.advisory_id, "riskScore": q.risk_score,
             "riskTier": q.risk_tier, "payload": q.payload}
            for q in items
        ]}


# ── Escalation checker (10-min timeout → secondary OC) ──────────────────────
def _escalation_loop() -> None:
    while True:
        time.sleep(30)
        now = time.monotonic()
        with _queue_lock:
            for qa in list(_queue.values()):
                if not qa.escalated and (now - qa.created_at) > ESCALATION_TIMEOUT_S:
                    qa.escalated = True
                    log.warning("ADVISORY_ESCALATED id=%s", qa.advisory_id)
                    _publish_alert({
                        "alertType":   "ADVISORY_ESCALATION",
                        "advisoryId":  qa.advisory_id,
                        "reason":      "No action taken within 10 minutes",
                    })


# ── Forward authorized advisory downstream ───────────────────────────────────
def _forward_advisory(qa: _QueuedAdvisory, second_controller: str) -> None:
    """Forward advisory to maintenance dispatch / ops workflow via Kafka."""
    enriched = {**qa.payload, "authorized": True,
                "riskScore": qa.risk_score, "riskTier": qa.risk_tier}
    _publish_kafka("ops.advisories.authorized", enriched)
    log.info("Advisory FORWARDED id=%s tier=%d", qa.advisory_id, qa.risk_tier)


def _publish_alert(payload: dict) -> None:
    _publish_kafka("monitoring.alerts", payload)


def _publish_kafka(topic: str, payload: dict) -> None:
    try:
        from kafka import KafkaProducer
        p = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all", retries=3)
        p.send(topic, value=json.dumps(payload).encode())
        p.flush(timeout=5)
    except Exception as exc:
        log.error("Kafka publish %s failed: %s", topic, exc)


def _write_audit_log(advisory_id: str, action: str, controller_id: str,
                      qa: _QueuedAdvisory) -> None:
    record = {
        "auditId":       str(uuid.uuid4()),
        "advisoryId":    advisory_id,
        "action":        action,
        "controllerIdentity": controller_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "riskTier":      qa.risk_tier,
        "riskScore":     qa.risk_score,
    }
    try:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO authorization_audit "
                "(audit_id, advisory_id, action, controller_identity, timestamp_utc, risk_tier, risk_score) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (record["auditId"], advisory_id, action, controller_id,
                 record["timestamp_utc"], qa.risk_tier, qa.risk_score),
            )
        conn.commit(); conn.close()
    except Exception as exc:
        log.error("Audit log write failed: %s", exc)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
