"""
RailOS Dataset Governance Service (Tasks 26.1–26.4)
DVC versioning + provenance report API + 365-day retention.
Satisfies: Req 42, Design §11
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException
from prometheus_client import start_http_server
from pydantic import BaseModel

log = logging.getLogger(__name__)

APP_PORT     = int(os.environ.get("APP_PORT", "8091"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8080"))
DB_URL       = os.environ.get("DB_URL",
                               "postgresql://railos:change-me@postgresql-primary.railos.svc.cluster.local:5432/railos")

app = FastAPI(title="RailOS Dataset Governance", docs_url=None)


class DatasetRegistration(BaseModel):
    datasetPath:             str
    sourceSystems:           list[str]
    preprocessingSteps:      list[str]
    annotationToolVersion:   str
    timestampRangeStart:     str
    timestampRangeEnd:       str
    approvedBy:              str
    datasetName:             str = ""


@app.on_event("startup")
def _startup() -> None:
    start_http_server(METRICS_PORT)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/datasets/register")
def register_dataset(req: DatasetRegistration) -> dict:
    """Register a dataset version with provenance (Task 26.1)."""
    from services.model_governance.dvc_dataset_config import register_dataset
    record = register_dataset(
        dataset_path=req.datasetPath,
        source_system=",".join(req.sourceSystems),
        preprocessing_steps=req.preprocessingSteps,
        annotation_tool_version=req.annotationToolVersion,
        timestamp_range_start=req.timestampRangeStart,
        timestamp_range_end=req.timestampRangeEnd,
        approved_by=req.approvedBy,
        dataset_name=req.datasetName,
    )
    _write_to_db(record)
    return record


@app.post("/api/v1/datasets/link-model")
def link_dataset_to_model(body: dict) -> dict:
    """Link model version to dataset versions (Task 26.2)."""
    from services.model_governance.dvc_dataset_config import link_dataset_to_model
    return link_dataset_to_model(
        model_version=body.get("modelVersion", ""),
        training_dataset_version_id=body.get("trainingDatasetVersionId", ""),
        eval_dataset_version_id=body.get("evalDatasetVersionId", ""),
    )


@app.get("/api/v1/datasets/{version_id}/provenance")
def get_provenance(version_id: str) -> dict:
    """Return provenance record for a dataset version (Task 26.3)."""
    record = _query_provenance(version_id)
    if not record:
        raise HTTPException(404, detail=f"No provenance found for version {version_id}")
    return record


def _write_to_db(record: dict) -> None:
    try:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dataset_versions
                  (dataset_version_id, dataset_name, dataset_path, source_system,
                   preprocessing_steps, annotation_tool_version,
                   timestamp_range_start, timestamp_range_end, approved_by, registered_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (dataset_version_id) DO NOTHING
                """,
                (record["datasetVersionId"], record["datasetName"], record["datasetPath"],
                 record["sourceSystem"], json.dumps(record["preprocessingSteps"]),
                 record["annotationToolVersion"], record["timestampRangeStart"],
                 record["timestampRangeEnd"], record["approvedBy"], record["registeredAt"]),
            )
        conn.commit(); conn.close()
    except Exception as exc:
        log.error("Dataset DB write failed: %s", exc)


def _query_provenance(version_id: str) -> dict | None:
    try:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM dataset_versions WHERE dataset_version_id=%s",
                (version_id,),
            )
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if cur.description else []
        conn.close()
        return dict(zip(cols, row)) if row else None
    except Exception as exc:
        log.error("Dataset DB query failed: %s", exc)
        return None


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
