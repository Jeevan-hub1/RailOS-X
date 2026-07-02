"""
RailOS Human-in-the-Loop Authorization Gate (Tasks 14.1-14.8)
Structural boundary: no advisory reaches any operational system without OC authorization.

Enhanced features:
  - Time-in-queue tracking with countdown to escalation
  - Controller roles (Senior OC, OC, Supervisor) with permission levels
  - Statistics endpoint (throughput, avg decision time, tier breakdown)
  - Richer queue response (age, escalation countdown, source system)
  - Audit trail with full decision context
  - Auto-escalation with configurable timeouts per tier

Satisfies: Req 12, Req 30, Req 40, Design section 12
"""
from __future__ import annotations
import json, logging, os, sys, threading, time, uuid
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Optional
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.risk_scoring import compute_risk_score as _compute_risk_score, compute_risk_tier, SEVERITY_WEIGHTS
from common.logging_config import configure_logging
from common.datetime_utils import now_iso

configure_logging()
log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
    "railos-kafka-kafka-bootstrap.railos.svc.cluster.local:9092")
DB_URL = os.environ.get("DB_URL",
    "postgresql://railos:change-me@postgresql-primary.railos.svc.cluster.local:5432/railos")
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8080"))
APP_PORT = int(os.environ.get("APP_PORT", "8086"))

# Tier-specific escalation timeouts (seconds)
ESCALATION_TIMEOUTS = {
    1: float(os.environ.get("TIER1_ESCALATION_S", "300")),
    2: float(os.environ.get("TIER2_ESCALATION_S", "600")),
    3: float(os.environ.get("TIER3_ESCALATION_S", "900")),
}

# Prometheus
gate_status_gauge = Gauge("railos_authorization_gate_status", "0=unavail,1=degraded,2=operational")
advisories_authorized = Counter("advisories_authorized_total", "Advisories authorized")
advisories_rejected = Counter("advisories_rejected_total", "Advisories rejected")
tier1_dual_auth = Counter("tier1_dual_auth_completions_total", "Tier 1 dual-auth completions")
decision_latency = Histogram("gate_decision_latency_seconds", "Enqueue to decision time",
                             buckets=[10, 30, 60, 120, 300, 600, 900])
queue_depth_gauge = Gauge("gate_queue_depth", "Current advisory queue depth")
escalations_total = Counter("gate_escalations_total", "Escalation events", ["tier"])

# ── Kafka producer singleton ─────────────────────────────────────────────────
_kafka_producer = None

def _get_producer():
    global _kafka_producer
    if _kafka_producer is not None:
        return _kafka_producer
    try:
        from kafka import KafkaProducer
        _kafka_producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, acks="all",
            retries=3, linger_ms=10, compression_type="lz4", max_block_ms=5000)
        return _kafka_producer
    except Exception as exc:
        log.error("Kafka producer init failed: %s", exc)
        return None

# ── DB connection pool ───────────────────────────────────────────────────────
_db_pool = None
_db_pool_lock = threading.Lock()

def _get_db_connection():
    global _db_pool
    if _db_pool is None:
        with _db_pool_lock:
            if _db_pool is None:
                try:
                    import psycopg2.pool
                    _db_pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=5, dsn=DB_URL)
                except Exception as exc:
                    log.error("DB pool init failed: %s", exc)
                    return None
    try:
        return _db_pool.getconn()
    except Exception as exc:
        log.error("DB connection acquisition failed: %s", exc)
        return None

def _return_db_connection(conn):
    if _db_pool and conn:
        try:
            _db_pool.putconn(conn)
        except Exception as exc:
            log.warning("Failed to return DB connection to pool: %s", exc)

# ── Controller Roles ─────────────────────────────────────────────────────────
CONTROLLER_ROLES = {
    "SENIOR_OC":  {"level": 1, "can_authorize_tier": [1, 2, 3], "dual_auth_eligible": True},
    "OC":         {"level": 2, "can_authorize_tier": [2, 3], "dual_auth_eligible": True},
    "SUPERVISOR": {"level": 3, "can_authorize_tier": [3], "dual_auth_eligible": False},
}

KNOWN_CONTROLLERS = {
    "OC-Sharma-001": {"name": "R.K. Sharma", "role": "SENIOR_OC", "station": "NDLS"},
    "OC-Patel-002":  {"name": "A.V. Patel", "role": "SENIOR_OC", "station": "NDLS"},
    "OC-Kumar-003":  {"name": "S. Kumar", "role": "OC", "station": "GZB"},
    "OC-Singh-004":  {"name": "J. Singh", "role": "OC", "station": "MERT"},
    "SUP-Reddy-005": {"name": "P. Reddy", "role": "SUPERVISOR", "station": "ANVT"},
}

# ── Risk scoring ─────────────────────────────────────────────────────────────
def _gate_risk_score(probability: float, severity: str) -> float:
    w = SEVERITY_WEIGHTS.get(severity.upper(), 1)
    return _compute_risk_score(probability, w)

def risk_tier(score: float) -> int:
    return compute_risk_tier(score)

# ── Advisory queue ───────────────────────────────────────────────────────────
class _QueuedAdvisory:
    __slots__ = ('advisory_id', 'payload', 'risk_score', 'risk_tier',
                 'created_at', 'created_utc', 'first_auth_by', 'first_auth_at',
                 'escalated', 'escalation_count', 'source_system', 'severity')
    def __init__(self, advisory_id, payload, score, tier, severity="HIGH", source="unknown"):
        self.advisory_id = advisory_id
        self.payload = payload
        self.risk_score = score
        self.risk_tier = tier
        self.created_at = time.monotonic()
        self.created_utc = now_iso()
        self.first_auth_by = None
        self.first_auth_at = None
        self.escalated = False
        self.escalation_count = 0
        self.source_system = source
        self.severity = severity

_queue: OrderedDict[str, _QueuedAdvisory] = OrderedDict()
_queue_lock = threading.Lock()
_gate_operational = True
_queue_sorted_cache: list[_QueuedAdvisory] = []
_queue_dirty = True

# ── Statistics tracking ──────────────────────────────────────────────────────
_stats_lock = threading.Lock()
_stats = {"total_enqueued": 0, "total_authorized": 0, "total_rejected": 0,
          "total_escalated": 0, "decision_times_s": deque(maxlen=200),
          "tier_breakdown": {1: 0, 2: 0, 3: 0}}
_audit_log: deque = deque(maxlen=100)

# ── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(title="RailOS Authorization Gate", docs_url=None, redoc_url=None)
_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001",
).split(",")
app.add_middleware(CORSMiddleware, allow_origins=_ALLOWED_ORIGINS, allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

class AuthorizeRequest(BaseModel):
    advisoryId: str
    controllerId: str
    action: str
    reason: str = ""

class EnqueueRequest(BaseModel):
    advisoryId: str
    payload: dict
    probability: float = 0.5
    severity: str = "HIGH"
    source: str = "ml_subsystem"

@app.on_event("startup")
def _startup():
    start_http_server(METRICS_PORT)
    gate_status_gauge.set(2)
    threading.Thread(target=_escalation_loop, daemon=True).start()

@app.get("/health")
def health():
    return {"status": "ok", "gate": "operational" if _gate_operational else "unavailable",
            "queueDepth": len(_queue)}

@app.post("/api/v1/gate/enqueue")
def enqueue_advisory(req: EnqueueRequest):
    global _queue_dirty
    score = _gate_risk_score(req.probability, req.severity)
    tier = risk_tier(score)
    qa = _QueuedAdvisory(req.advisoryId, req.payload, score, tier, req.severity, req.source)
    with _queue_lock:
        _queue[req.advisoryId] = qa
        _queue_dirty = True
    queue_depth_gauge.set(len(_queue))
    with _stats_lock:
        _stats["total_enqueued"] += 1
        _stats["tier_breakdown"][tier] = _stats["tier_breakdown"].get(tier, 0) + 1
    log.info("Advisory enqueued id=%s score=%.2f tier=%d", req.advisoryId, score, tier)
    return {"advisoryId": req.advisoryId, "riskScore": round(score, 2), "riskTier": tier,
            "escalationTimeoutS": ESCALATION_TIMEOUTS.get(tier, 600)}

@app.post("/api/v1/gate/authorize")
def authorize(req: AuthorizeRequest):
    global _gate_operational, _queue_dirty
    if not _gate_operational:
        raise HTTPException(503, detail="Authorization gate is unavailable")
    controller_info = KNOWN_CONTROLLERS.get(req.controllerId,
        {"name": req.controllerId, "role": "OC", "station": "UNKNOWN"})
    role_info = CONTROLLER_ROLES.get(controller_info["role"], CONTROLLER_ROLES["OC"])
    with _queue_lock:
        qa = _queue.get(req.advisoryId)
        if qa is None:
            raise HTTPException(404, detail="Advisory not found in queue")
        if qa.risk_tier not in role_info["can_authorize_tier"]:
            raise HTTPException(403, detail=f"Role {controller_info['role']} cannot authorize Tier {qa.risk_tier}")
        decision_time_s = time.monotonic() - qa.created_at
        if req.action.upper() == "AUTHORIZE":
            if qa.risk_tier == 1:
                if qa.first_auth_by is None:
                    qa.first_auth_by = req.controllerId
                    qa.first_auth_at = datetime.now(timezone.utc).isoformat()
                    return {"status": "AWAITING_SECOND_AUTH", "firstAuthBy": req.controllerId,
                            "firstAuthName": controller_info["name"]}
                if qa.first_auth_by == req.controllerId:
                    raise HTTPException(400, detail="Second auth must be from different controller")
                _forward_advisory(qa, req.controllerId)
                del _queue[req.advisoryId]; _queue_dirty = True
                tier1_dual_auth.inc()
            else:
                _forward_advisory(qa, req.controllerId)
                del _queue[req.advisoryId]; _queue_dirty = True
            advisories_authorized.inc()
            decision_latency.observe(decision_time_s)
            _record_decision(req.advisoryId, "AUTHORIZE", req.controllerId, controller_info, qa, decision_time_s, req.reason)
            queue_depth_gauge.set(len(_queue))
            return {"status": "AUTHORIZED", "advisoryId": req.advisoryId,
                    "decisionTimeS": round(decision_time_s, 1), "authorizedBy": controller_info["name"]}
        elif req.action.upper() == "REJECT":
            del _queue[req.advisoryId]; _queue_dirty = True
            advisories_rejected.inc()
            decision_latency.observe(decision_time_s)
            _record_decision(req.advisoryId, "REJECT", req.controllerId, controller_info, qa, decision_time_s, req.reason)
            queue_depth_gauge.set(len(_queue))
            return {"status": "REJECTED", "advisoryId": req.advisoryId,
                    "decisionTimeS": round(decision_time_s, 1), "rejectedBy": controller_info["name"]}
        raise HTTPException(400, detail="action must be AUTHORIZE or REJECT")

@app.get("/api/v1/gate/queue")
def get_queue():
    global _queue_sorted_cache, _queue_dirty
    now = time.monotonic()
    with _queue_lock:
        if _queue_dirty:
            _queue_sorted_cache = sorted(_queue.values(), key=lambda q: -q.risk_score)
            _queue_dirty = False
        return {"advisories": [{
            "advisoryId": q.advisory_id, "riskScore": round(q.risk_score, 2),
            "riskTier": q.risk_tier, "severity": q.severity, "payload": q.payload,
            "source": q.source_system, "createdUtc": q.created_utc,
            "ageSeconds": round(now - q.created_at),
            "escalated": q.escalated, "escalationCount": q.escalation_count,
            "escalationTimeoutS": ESCALATION_TIMEOUTS.get(q.risk_tier, 600),
            "timeToEscalationS": max(0, round(ESCALATION_TIMEOUTS.get(q.risk_tier, 600) - (now - q.created_at))),
            "awaitingSecondAuth": q.first_auth_by is not None,
            "firstAuthBy": q.first_auth_by, "firstAuthAt": q.first_auth_at,
        } for q in _queue_sorted_cache]}

@app.get("/api/v1/gate/stats")
def get_stats():
    with _stats_lock:
        dt = list(_stats["decision_times_s"])
        avg_d = sum(dt) / len(dt) if dt else 0
        return {
            "totalEnqueued": _stats["total_enqueued"],
            "totalAuthorized": _stats["total_authorized"],
            "totalRejected": _stats["total_rejected"],
            "totalEscalated": _stats["total_escalated"],
            "currentQueueDepth": len(_queue),
            "avgDecisionTimeS": round(avg_d, 1),
            "tierBreakdown": dict(_stats["tier_breakdown"]),
            "authorizationRate": round(
                _stats["total_authorized"] / max(1, _stats["total_authorized"] + _stats["total_rejected"]) * 100, 1),
            "escalationTimeouts": ESCALATION_TIMEOUTS,
        }

@app.get("/api/v1/gate/audit")
def get_audit():
    return {"entries": list(_audit_log)}

@app.get("/api/v1/gate/controllers")
def get_controllers():
    return {"controllers": [
        {"id": cid, "name": c["name"], "role": c["role"], "station": c["station"]}
        for cid, c in KNOWN_CONTROLLERS.items()
    ]}

# ── Escalation loop ──────────────────────────────────────────────────────────
def _escalation_loop():
    while True:
        time.sleep(15)
        now = time.monotonic()
        with _queue_lock:
            for qa in list(_queue.values()):
                timeout = ESCALATION_TIMEOUTS.get(qa.risk_tier, 600)
                if (now - qa.created_at) > timeout * (qa.escalation_count + 1):
                    if qa.escalation_count < 3:
                        qa.escalated = True
                        qa.escalation_count += 1
                        log.warning("ADVISORY_ESCALATED id=%s tier=%d count=%d",
                                    qa.advisory_id, qa.risk_tier, qa.escalation_count)
                        escalations_total.labels(tier=str(qa.risk_tier)).inc()
                        with _stats_lock:
                            _stats["total_escalated"] += 1
                        _publish_kafka("monitoring.alerts", {
                            "alertType": "ADVISORY_ESCALATION",
                            "advisoryId": qa.advisory_id, "riskTier": qa.risk_tier,
                            "escalationCount": qa.escalation_count,
                            "ageSeconds": round(now - qa.created_at),
                        })

# ── Internal helpers ─────────────────────────────────────────────────────────
def _forward_advisory(qa, controller_id):
    enriched = {**qa.payload, "authorized": True,
                "riskScore": qa.risk_score, "riskTier": qa.risk_tier,
                "authorizedBy": controller_id}
    _publish_kafka("ops.advisories.authorized", enriched)
    log.info("Advisory FORWARDED id=%s tier=%d", qa.advisory_id, qa.risk_tier)

def _record_decision(advisory_id, action, controller_id, controller_info, qa, decision_time_s, reason):
    with _stats_lock:
        if action == "AUTHORIZE": _stats["total_authorized"] += 1
        else: _stats["total_rejected"] += 1
        _stats["decision_times_s"].append(decision_time_s)
    entry = {"auditId": str(uuid.uuid4()), "advisoryId": advisory_id, "action": action,
             "controllerId": controller_id, "controllerName": controller_info.get("name", ""),
             "controllerRole": controller_info.get("role", ""),
             "timestamp_utc": now_iso(),
             "riskTier": qa.risk_tier, "riskScore": round(qa.risk_score, 2),
             "decisionTimeS": round(decision_time_s, 1), "reason": reason,
             "wasEscalated": qa.escalated}
    _audit_log.append(entry)

def _publish_kafka(topic, payload):
    producer = _get_producer()
    if producer is None: return
    try:
        producer.send(topic, value=json.dumps(payload).encode())
    except Exception as exc:
        log.error("Kafka publish %s failed: %s", topic, exc)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
