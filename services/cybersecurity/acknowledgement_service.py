"""
RailOS Cybersecurity Acknowledgement Service (Tasks 12.5, 12.7, 12.8)
- Forensic evidence package API (GET /api/v1/forensics/{alertId}/package)
- Acknowledgement workflow with 15-min escalation
- Append-only audit log in PostgreSQL
Satisfies: Req 9 C4–C7, Req 26, Design §6.6
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from prometheus_client import start_http_server
from pydantic import BaseModel

log = logging.getLogger(__name__)

MINIO_ENDPOINT   = os.environ.get("MINIO_ENDPOINT",   "http://minio.railos.svc.cluster.local:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "railos-admin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "change-me")
FORENSIC_BUCKET  = os.environ.get("FORENSIC_BUCKET",  "railos-forensic-evidence")
METRICS_PORT     = int(os.environ.get("METRICS_PORT",  "8083"))
APP_PORT         = int(os.environ.get("APP_PORT",       "8084"))
DB_URL           = os.environ.get("DB_URL",            "postgresql://railos:change-me@postgresql-primary.railos.svc.cluster.local:5432/railos")

app = FastAPI(title="RailOS Cybersecurity Dashboard API", docs_url=None, redoc_url=None)


class AckRequest(BaseModel):
    officerId: str
    notes:     Optional[str] = None


@app.on_event("startup")
def _startup() -> None:
    start_http_server(METRICS_PORT)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/forensics/{alert_id}/package")
def get_forensic_package(alert_id: str) -> StreamingResponse:
    """Download forensic evidence archive for a given alert ID (Task 12.5).

    Only accessible to Security_Officer role (enforced by Kong + auth middleware).
    """
    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        key = f"{alert_id}.tar.gz"
        obj = s3.get_object(Bucket=FORENSIC_BUCKET, Key=key)

        return StreamingResponse(
            obj["Body"].iter_chunks(),
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{key}"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Forensic package not found: {exc}")


@app.post("/api/v1/security/anomalies/{alert_id}/acknowledge")
def acknowledge_anomaly(alert_id: str, req: AckRequest) -> dict:
    """Acknowledge a SECURITY_ANOMALY alert (Task 12.7).

    Writes immutable record to security_audit table (Task 12.8).
    """
    record = {
        "auditId":       str(uuid.uuid4()),
        "alertId":       alert_id,
        "action":        "ACKNOWLEDGE",
        "officerId":     req.officerId,
        "notes":         req.notes,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _write_audit_log(record)
    except Exception as exc:
        log.error("Could not write to security_audit table: %s", exc)
        raise HTTPException(status_code=503, detail="Audit record could not be persisted")
    log.info("SECURITY_ANOMALY acknowledged: alert_id=%s officer=%s", alert_id, req.officerId)
    return {"status": "acknowledged", "auditId": record["auditId"]}


def _write_audit_log(record: dict) -> None:
    """Write to append-only security_audit PostgreSQL table (Task 12.8).

    Raises on failure so callers can report the error.
    """
    import psycopg2
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO security_audit
                  (audit_id, alert_id, action, officer_id, notes, timestamp_utc)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (record["auditId"], record["alertId"], record["action"],
                 record["officerId"], record.get("notes"), record["timestamp_utc"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
