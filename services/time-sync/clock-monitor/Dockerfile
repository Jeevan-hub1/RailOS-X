FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libc6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY clock_monitor.py .

USER 1000
CMD ["python", "clock_monitor.py"]
