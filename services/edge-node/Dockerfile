# RailOS Edge Node Container (Task 5.6)
# Ubuntu 22.04 LTS · Python 3.11 · containerd-compatible · non-root UID 1000
# Satisfies: Req 2 (autonomous operation), Req 44 (hardware telemetry)

FROM ubuntu:22.04

LABEL org.opencontainers.image.title="railos-edge-node" \
      org.opencontainers.image.description="RailOS Tier-2 Edge Node Agent" \
      org.opencontainers.image.vendor="RailOS Project"

# ── System packages ────────────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3-pip \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Make python3.11 the default python
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
 && update-alternatives --install /usr/bin/python  python  /usr/bin/python3.11 1

# ── Non-root user ──────────────────────────────────────────────────────────────
RUN groupadd --gid 1000 railos \
 && useradd  --uid 1000 --gid railos --shell /bin/bash --create-home railos

# ── App directory & Python dependencies ───────────────────────────────────────
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

# ── Copy edge-node source modules ─────────────────────────────────────────────
COPY buffer/       buffer/
COPY heartbeat/    heartbeat/
COPY uploader/     uploader/
COPY model_store/  model_store/
COPY alerter/      alerter/
COPY main.py       main.py

# ── Persistent data volumes ────────────────────────────────────────────────────
# /data/buffer  – SQLite circular event buffer
# /data/models  – NVMe-backed model weight store
# /data/logs    – Structured JSON log files and audit logs
VOLUME ["/data/buffer", "/data/models", "/data/logs"]

# ── Runtime configuration ──────────────────────────────────────────────────────
ENV PIPELINE_URL=""
ENV BUFFER_DB_PATH="/data/buffer/events.db"
ENV MODEL_STORE_PATH="/data/models"
ENV SMS_GATEWAY_URL=""
ENV METRICS_PORT="8080"
ENV ALERT_LOG_PATH="/data/logs/storage_alerts.jsonl"

EXPOSE 8080

# ── Drop to non-root ───────────────────────────────────────────────────────────
USER railos

ENTRYPOINT ["python", "main.py"]
