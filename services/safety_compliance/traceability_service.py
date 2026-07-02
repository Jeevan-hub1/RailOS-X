"""
RailOS Safety & Compliance — Traceability Matrix API (Tasks 21.1–21.2)
Satisfies: Req 35, Design §13.1
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from prometheus_client import start_http_server
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.db_utils import pg_connection
from common.datetime_utils import now_iso

log = logging.getLogger(__name__)
APP_PORT     = int(os.environ.get("APP_PORT", "8087"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8080"))

app = FastAPI(title="RailOS Traceability API", docs_url=None)


class TraceabilityRecord(BaseModel):
    requirementId:    str
    hazardIds:        list[str] = []
    mitigations:      list[str] = []
    mlflowRunId:      Optional[str] = None
    subsystemVersion: Optional[str] = None
    evidenceResult:   str = "PASS"  # PASS | FAIL


@app.on_event("startup")
def _startup() -> None:
    start_http_server(METRICS_PORT)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/traceability/record")
def create_record(rec: TraceabilityRecord) -> dict:
    """Create a traceability matrix entry (Task 21.1)."""
    trace_id = str(uuid.uuid4())
    entry = {
        "traceId":         trace_id,
        "requirementId":   rec.requirementId,
        "hazardIds":       rec.hazardIds,
        "mitigations":     rec.mitigations,
        "mlflowRunId":     rec.mlflowRunId,
        "deployedVersion": rec.subsystemVersion,
        "result":          rec.evidenceResult,
        "timestamp_utc":   now_iso(),
    }
    try:
        _write_to_db(entry)
    except Exception as exc:
        log.error("Traceability DB write failed: %s", exc)
        raise HTTPException(status_code=503, detail="Traceability record could not be persisted")
    return entry


@app.get("/api/v1/traceability/{subsystem_version}")
def get_report(subsystem_version: str) -> dict:
    """Generate traceability report for a subsystem version (Task 21.2)."""
    try:
        records = _query_db(subsystem_version)
    except Exception as exc:
        log.error("Traceability DB query failed: %s", exc)
        raise HTTPException(status_code=503, detail="Traceability database unavailable")
    if not records:
        raise HTTPException(404, detail=f"No traceability records for version {subsystem_version}")
    return {
        "subsystemVersion": subsystem_version,
        "requirements":     records,
        "generatedAt":      now_iso(),
    }


def _write_to_db(entry: dict) -> None:
    """Write traceability entry to DB. Raises on failure so callers can report errors."""
    with pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO traceability_matrix
                  (trace_id, requirement_id, hazard_ids, mitigations,
                   mlflow_run_id, deployed_version, result, timestamp_utc)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (entry["traceId"], entry["requirementId"],
                 json.dumps(entry["hazardIds"]), json.dumps(entry["mitigations"]),
                 entry.get("mlflowRunId"), entry.get("deployedVersion"),
                 entry["result"], entry["timestamp_utc"]),
            )


def _query_db(version: str) -> list[dict]:
    """Query traceability records. Raises on failure so callers can report errors."""
    with pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trace_id, requirement_id, result FROM traceability_matrix "
                "WHERE deployed_version=%s ORDER BY timestamp_utc DESC",
                (version,),
            )
            rows = cur.fetchall()
        return [{"traceId": r[0], "requirementId": r[1], "result": r[2]} for r in rows]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
