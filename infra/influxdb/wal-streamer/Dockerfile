# InfluxDB WAL Streamer / Receiver — Reference Image
#
# This image provides both the wal-streamer (primary sidecar) and wal-receiver
# (standby sidecar) roles. The ROLE environment variable selects the mode:
#   ROLE=streamer  → tails WAL dir and forwards segments to standby
#   ROLE=receiver  → listens on TCP port for incoming WAL segments and applies them
#
# Build:
#   docker build -t railos/influxdb-wal-streamer:1.0.0 infra/influxdb/wal-streamer/
#   docker tag railos/influxdb-wal-streamer:1.0.0 <registry>/railos/influxdb-wal-streamer:1.0.0
#   docker push <registry>/railos/influxdb-wal-streamer:1.0.0
#
# Also tag as wal-receiver (same image, different tag for clarity):
#   docker tag railos/influxdb-wal-streamer:1.0.0 <registry>/railos/influxdb-wal-receiver:1.0.0

FROM debian:12-slim

# Install runtime dependencies:
#   inotify-tools  — file-system event monitoring for WAL segment detection
#   ncat (nmap)    — reliable TCP transport for WAL segment forwarding
#   rsync          — file copy with checksum verification
#   curl           — health check and InfluxDB API calls
#   python3        — metrics HTTP server (exposes replication lag on /metrics)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       inotify-tools=3.22.6.0-4 \
       ncat=7.93+dfsg1-1 \
       rsync=3.2.7-1 \
       curl=7.88.1-10+deb12u7 \
       python3=3.11.2-1+b1 \
       python3-pip=23.0.1+dfsg-1 \
    && pip3 install --no-cache-dir prometheus-client==0.20.0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user matching the security context in the StatefulSet
RUN groupadd -g 1000 influxdb \
    && useradd -u 1000 -g 1000 -s /bin/bash -d /home/influxdb influxdb

WORKDIR /opt/wal-streamer

# Copy scripts
COPY --chown=1000:1000 wal-stream.sh   ./wal-stream.sh
COPY --chown=1000:1000 wal-receive.sh  ./wal-receive.sh
COPY --chown=1000:1000 metrics.py      ./metrics.py
COPY --chown=1000:1000 entrypoint.sh   ./entrypoint.sh

RUN chmod +x ./wal-stream.sh ./wal-receive.sh ./entrypoint.sh

USER 1000

# The entrypoint selects streamer or receiver mode via ROLE env var
ENTRYPOINT ["/opt/wal-streamer/entrypoint.sh"]
