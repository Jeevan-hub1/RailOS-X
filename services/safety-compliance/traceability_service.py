"""
RailOS Safety & Compliance — Traceability Matrix API (Tasks 21.1–21.2)
Satisfies: Req 35, Design §13.1
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from prometheus_client import start_http_server
from pydantic import BaseModel

log = logging.getLogger(__name__)
DB_URL       = os.environ.get("DB_URL", "postgresql://railos:change-me@postgresql-primary.railos.svc.cluster.local:5432/railos")
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
        "timestamp_utc":   datetime.now(timezone.utc).isoformat(),
    }
    _write_to_db(entry)
    return entry


@app.get("/api/v1/traceability/{subsystem_version}")
def get_report(subsystem_version: str) -> dict:
    """Generate traceability report for a subsystem version (Task 21.2)."""
    records = _query_db(subsystem_version)
    if not records:
        raise HTTPException(404, detail=f"No traceability records for version {subsystem_version}")
    return {
        "subsystemVersion": subsystem_version,
        "requirements":     records,
        "generatedAt":      datetime.now(timezone.utc).isoformat(),
    }


def _write_to_db(entry: dict) -> None:
    try:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
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
        conn.commit(); conn.close()
    except Exception as exc:
        log.error("Traceability DB write failed: %s", exc)


def _query_db(version: str) -> list[dict]:
    try:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trace_id, requirement_id, result FROM traceability_matrix "
                "WHERE deployed_version=%s ORDER BY timestamp_utc DESC",
                (version,),
            )
            rows = cur.fetchall()
        conn.close()
        return [{"traceId": r[0], "requirementId": r[1], "result": r[2]} for r in rows]
    except Exception as exc:
        log.error("Traceability DB query failed: %s", exc)
        return []


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
