"""
RailOS GNN Delay Predictor — FastAPI REST Service (Task 8.6)
POST /api/v1/delay-predictor/forecast
Satisfies: Req 5 C1 C3 C4 C5, Design §6.3
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, start_http_server
from pydantic import BaseModel, Field

from ..data.graph_builder import build_corridor_graph
from ..model.conformal_predictor import ConformalDelayPredictor
from ..model.hetgnn_model import HetGNN
from .ntes_consumer import NTESConsumer

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)

# ── Config ─────────────────────────────────────────────────────────────────────
MODEL_PATH            = os.environ.get("MODEL_PATH", "/models/hetgnn_v1.0.0.pt")
MODEL_VERSION         = os.environ.get("MODEL_VERSION", "1.0.0")
STALE_THRESHOLD_S     = float(os.environ.get("STALE_THRESHOLD_SECONDS", "60"))
METRICS_PORT          = int(os.environ.get("METRICS_PORT", "8080"))
APP_PORT              = int(os.environ.get("APP_PORT", "8081"))

# ── Prometheus ──────────────────────────────────────────────────────────────────
inference_latency_ms  = Histogram("delay_inference_latency_ms",  "Delay predictor inference latency",
                                  buckets=[50, 100, 250, 500, 1000, 2000, 5000])
forecasts_served      = Counter("forecasts_served_total",         "Total delay forecasts served")
stale_input_total     = Counter("stale_input_total",              "Forecasts served with STALE_INPUT flag")

# ── Models ──────────────────────────────────────────────────────────────────────

class TrainInput(BaseModel):
    trainId:            str
    current_delay_min:  float = 0.0
    load_factor:        float = Field(0.5, ge=0.0, le=1.0)
    schedule_adherence: float = Field(1.0, ge=0.0, le=1.0)
    stationId:          Optional[str] = None
    segmentId:          Optional[str] = None


class ForecastRequest(BaseModel):
    trains:   Optional[list[TrainInput]] = None  # if None, uses live NTES snapshot
    stations: Optional[list[dict]]       = None
    segments: Optional[list[dict]]       = None


class TrainForecast(BaseModel):
    trainId:      str
    delayMinutes: float
    ci_lower:     float
    ci_upper:     float
    stale_input:  bool


class ForecastResponse(BaseModel):
    forecasts:      list[TrainForecast]
    model_version:  str
    timestamp_utc:  str


# ── App ─────────────────────────────────────────────────────────────────────────
app = FastAPI(title="RailOS Delay Predictor", docs_url=None, redoc_url=None)
ntes_consumer: NTESConsumer = NTESConsumer(stale_threshold_s=STALE_THRESHOLD_S)
_model: HetGNN | None = None
_predictor: ConformalDelayPredictor | None = None


@app.on_event("startup")
def _startup() -> None:
    global _model, _predictor
    start_http_server(METRICS_PORT)
    _model = HetGNN()
    if os.path.exists(MODEL_PATH):
        try:
            _model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
            log.info("HetGNN weights loaded from %s", MODEL_PATH)
        except Exception as exc:
            log.warning("Could not load weights: %s — using random init", exc)
    _model.eval()
    _predictor = ConformalDelayPredictor(_model)
    ntes_consumer.start()
    log.info("Delay predictor service started")


@app.on_event("shutdown")
def _shutdown() -> None:
    ntes_consumer.stop()


@app.exception_handler(RequestValidationError)
async def _validation_error(request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": [{"field": ".".join(str(loc) for loc in e["loc"]), "msg": e["msg"]}
                             for e in exc.errors()]},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/delay-predictor/forecast", response_model=ForecastResponse)
def forecast(req: ForecastRequest) -> ForecastResponse:
    global _predictor
    if _predictor is None:
        raise HTTPException(status_code=503, detail="Model not yet loaded")

    stale = False
    if req.trains is None:
        # Use live NTES snapshot
        snapshot, stale = ntes_consumer.get_snapshot()
        trains = list(snapshot.values())
    else:
        trains = [t.dict() for t in req.trains]

    if stale:
        stale_input_total.inc()

    stations = req.stations or []
    segments = req.segments or []

    t0 = time.monotonic()
    hetero_data = build_corridor_graph(trains, stations, segments)
    preds = _predictor.predict(hetero_data)
    elapsed_ms = (time.monotonic() - t0) * 1000
    inference_latency_ms.observe(elapsed_ms)
    forecasts_served.inc()

    # Map predictions back to train IDs
    train_ids = [t.get("trainId", str(i)) for i, t in enumerate(trains)]
    result_forecasts = []
    for idx, (point, ci_lo, ci_hi) in preds.items():
        tid = train_ids[idx] if idx < len(train_ids) else str(idx)
        result_forecasts.append(TrainForecast(
            trainId=tid,
            delayMinutes=point,
            ci_lower=ci_lo,
            ci_upper=ci_hi,
            stale_input=stale,
        ))

    return ForecastResponse(
        forecasts=result_forecasts,
        model_version=MODEL_VERSION,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
