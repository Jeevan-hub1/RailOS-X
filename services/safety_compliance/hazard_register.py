"""
RailOS Hazard Register (Task 21.3)
Append-only PostgreSQL table; HAZARD_REVIEW_REQUIRED trigger on repeated anomaly patterns.
Satisfies: Req 36, Design §13.2
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.db_utils import pg_connection
from common.datetime_utils import now_iso

log = logging.getLogger(__name__)
APP_PORT = int(os.environ.get("APP_PORT", "8088"))

app = FastAPI(title="RailOS Hazard Register", docs_url=None)


class HazardEntry(BaseModel):
    hazardId:         Optional[str] = None
    description:      str
    subsystem:        str
    likelihood:       str  # Low | Medium | High
    severity:         str  # Minor | Major | Catastrophic
    residualRisk:     str  = "Low"
    mitigation:       str
    approvalStatus:   str  = "Open"  # Open | Mitigated | Accepted | Closed
    evidenceRef:      Optional[str] = None
    createdBy:        str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/hazards")
def create_hazard(entry: HazardEntry) -> dict:
    """Append a new hazard entry (append-only — no UPDATE/DELETE allowed)."""
    hazard_id = entry.hazardId or f"HAZ-{str(uuid.uuid4())[:8].upper()}"
    record = {
        "revision_id":   str(uuid.uuid4()),
        "hazard_id":     hazard_id,
        "description":   entry.description,
        "subsystem":     entry.subsystem,
        "likelihood":    entry.likelihood,
        "severity":      entry.severity,
        "residual_risk": entry.residualRisk,
        "mitigation":    entry.mitigation,
        "approval_status": entry.approvalStatus,
        "evidence_ref":  entry.evidenceRef,
        "created_by":    entry.createdBy,
        "created_at":    now_iso(),
    }
    try:
        _insert_hazard(record)
    except Exception as exc:
        log.error("Hazard register insert failed: %s", exc)
        raise HTTPException(status_code=503, detail="Hazard record could not be persisted")
    return record


@app.get("/api/v1/hazards")
def list_hazards(subsystem: Optional[str] = None) -> dict:
    """List all hazard register entries."""
    try:
        entries = _query_hazards(subsystem)
    except Exception as exc:
        log.error("Hazard register query failed: %s", exc)
        raise HTTPException(status_code=503, detail="Hazard register database unavailable")
    return {"hazards": entries, "count": len(entries)}


@app.post("/api/v1/hazards/review-required")
def flag_for_review(payload: dict) -> dict:
    """Emit HAZARD_REVIEW_REQUIRED when anomaly patterns are detected."""
    log.warning("HAZARD_REVIEW_REQUIRED subsystem=%s pattern=%s",
                payload.get("subsystem"), payload.get("pattern"))
    return {"status": "HAZARD_REVIEW_REQUIRED", "flagged": True}


def _insert_hazard(record: dict) -> None:
    """Insert hazard record. Raises on failure so callers can report errors."""
    with pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hazard_register
                  (revision_id, hazard_id, description, subsystem, likelihood,
                   severity, residual_risk, mitigation, evidence_ref,
                   approval_status, created_at, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (record["revision_id"], record["hazard_id"], record["description"],
                 record["subsystem"], record["likelihood"], record["severity"],
                 record["residual_risk"], record["mitigation"], record.get("evidence_ref"),
                 record["approval_status"], record["created_at"], record["created_by"]),
            )


def _query_hazards(subsystem: Optional[str] = None) -> list[dict]:
    """Query hazard records. Raises on failure so callers can report errors."""
    with pg_connection() as conn:
        with conn.cursor() as cur:
            if subsystem:
                cur.execute(
                    "SELECT hazard_id, description, approval_status FROM hazard_register "
                    "WHERE subsystem=%s ORDER BY created_at DESC", (subsystem,)
                )
            else:
                cur.execute(
                    "SELECT hazard_id, description, approval_status FROM hazard_register "
                    "ORDER BY created_at DESC LIMIT 100"
                )
            rows = cur.fetchall()
        return [{"hazardId": r[0], "description": r[1], "approvalStatus": r[2]}
                for r in rows]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
