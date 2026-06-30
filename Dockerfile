# RailOS-X — generic image for the (non-ML) Python microservices.
#
# One image, many services: the service to run is provided as the container
# `command` in docker-compose (e.g. `python -m services.kavach_advisory.kavach_advisory`).
# ML-heavy services (delay_predictor, defect_detector, maintenance_engine,
# federated_learning) are run natively for now — see requirements-runtime.txt.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Minimal build deps for psycopg2 etc., removed after install to keep image slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-runtime.txt ./
RUN pip install --upgrade pip && pip install -r requirements-runtime.txt

COPY pyproject.toml ./
COPY services/ ./services/

# Non-root user.
RUN useradd --create-home --uid 10001 railos
USER railos

# Overridden per-service by docker-compose. Defaults to a helpful message.
CMD ["python", "-c", "print('Specify a service command, e.g. python -m services.kavach_advisory.kavach_advisory')"]
