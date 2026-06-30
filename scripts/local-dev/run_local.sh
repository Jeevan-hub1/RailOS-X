#!/usr/bin/env bash
###############################################################################
# RailOS-X — Local Development Launcher
#
# This script starts the full RailOS-X system locally:
#   1. Infrastructure (Kafka, PostgreSQL, InfluxDB, Redis, MinIO) via Docker
#   2. Python microservices (natively, against the Docker infra)
#   3. Digital Twin frontend (Next.js dev server)
#
# Usage:
#   ./scripts/local-dev/run_local.sh              # Full stack
#   ./scripts/local-dev/run_local.sh infra        # Infrastructure only
#   ./scripts/local-dev/run_local.sh services     # Services only (assumes infra running)
#   ./scripts/local-dev/run_local.sh tests        # Run property-based tests
#   ./scripts/local-dev/run_local.sh stop         # Stop everything
#
# Prerequisites:
#   - Docker / Podman with compose support
#   - Python 3.11+ with pip
#   - Node.js 18+ (for Digital Twin frontend)
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()  { echo -e "${GREEN}[RailOS]${NC} $*"; }
warn() { echo -e "${YELLOW}[RailOS]${NC} $*"; }
err()  { echo -e "${RED}[RailOS]${NC} $*" >&2; }

# ── Environment Variables for Local Dev ──────────────────────────────────────
export KAFKA_BOOTSTRAP_SERVERS="localhost:9092"
export DB_URL="postgresql://railos:railos-dev@localhost:5433/railos"
export INFLUXDB_URL="http://localhost:8086"
export INFLUXDB_TOKEN="railos-dev-token"
export INFLUXDB_ORG="railos"
export INFLUXDB_BUCKET="sensor-telemetry"
export REDIS_URL="redis://localhost:6379"
export MLFLOW_TRACKING_URI="http://localhost:5000"
export MINIO_ENDPOINT="http://localhost:9000"
export PYTHONPATH="$PROJECT_ROOT"

# ── Functions ────────────────────────────────────────────────────────────────

start_infra() {
    log "Starting infrastructure containers..."
    docker compose -f "$PROJECT_ROOT/docker-compose.yml" up -d
    
    log "Waiting for services to be healthy..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if docker compose -f "$PROJECT_ROOT/docker-compose.yml" ps | grep -q "healthy"; then
            break
        fi
        sleep 2
        retries=$((retries - 1))
    done
    
    log "Infrastructure ready!"
    echo ""
    echo "  Kafka:       localhost:9094"
    echo "  PostgreSQL:  localhost:5432  (railos/railos-dev)"
    echo "  InfluxDB:    localhost:8086  (token: railos-dev-token)"
    echo "  Redis:       localhost:6379"
    echo "  MinIO:       localhost:9000  (minioadmin/minioadmin)"
    echo "  MinIO UI:    localhost:9001"
    echo ""
}

stop_infra() {
    log "Stopping infrastructure..."
    docker compose -f "$PROJECT_ROOT/docker-compose.yml" down -v 2>/dev/null || true
}

install_deps() {
    log "Installing Python dependencies..."
    pip install -r "$PROJECT_ROOT/requirements-dev.txt" --quiet 2>/dev/null || \
    pip install -r "$PROJECT_ROOT/requirements-dev.txt"
}

start_services() {
    log "Starting RailOS microservices..."
    
    # Service ports:
    #   8081 - MARL Scheduler
    #   8082 - Kavach Advisory
    #   8083 - Maintenance Engine
    #   8084 - Delay Predictor
    #   8085 - Digital Twin WebSocket
    #   8086 - (reserved: InfluxDB)
    #   8087 - Authorization Gate
    #   8088 - Cybersecurity Anomaly
    
    log "  Starting Kavach Advisory (port 8082)..."
    APP_PORT=8082 METRICS_PORT=9082 python -m uvicorn \
        services.kavach_advisory.kavach_advisory:app \
        --host 0.0.0.0 --port 8082 &
    
    log "  Starting Authorization Gate (port 8087)..."
    APP_PORT=8087 METRICS_PORT=9087 python -m uvicorn \
        services.authorization_gate.gate_service:app \
        --host 0.0.0.0 --port 8087 &
    
    log "  Starting MARL Scheduler (port 8081)..."
    APP_PORT=8081 METRICS_PORT=9081 python -m uvicorn \
        services.marl_scheduler.service.scheduler_service:app \
        --host 0.0.0.0 --port 8081 &
    
    log ""
    log "Services started! Endpoints:"
    echo "  Kavach Advisory:     http://localhost:8082/health"
    echo "  Authorization Gate:  http://localhost:8087/health"
    echo "  MARL Scheduler:      http://localhost:8081/health"
    echo ""
    echo "  API docs (when running):"
    echo "    POST http://localhost:8082/api/v1/kavach-advisory"
    echo "    POST http://localhost:8087/api/v1/gate/enqueue"
    echo "    POST http://localhost:8087/api/v1/gate/authorize"
    echo "    GET  http://localhost:8087/api/v1/gate/queue"
    echo "    POST http://localhost:8081/api/v1/scheduler/propose"
    echo ""
    
    wait
}

run_tests() {
    log "Running RailOS Property-Based Tests (7 correctness invariants)..."
    cd "$PROJECT_ROOT"
    python -m pytest tests/pbt/test_all_properties.py -v --tb=short \
        -x --timeout=120 2>&1 || true
}

start_frontend() {
    log "Starting Digital Twin frontend..."
    cd "$PROJECT_ROOT/services/digital-twin/frontend"
    if [ ! -d "node_modules" ]; then
        npm install
    fi
    npx next dev --port 3001 &
    log "Digital Twin UI: http://localhost:3001"
}

show_help() {
    echo ""
    echo "RailOS-X Local Development Launcher"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  (none)     Start full stack (infra + services)"
    echo "  infra      Start infrastructure only (Docker containers)"
    echo "  services   Start Python services only (assumes infra running)"
    echo "  tests      Run property-based tests"
    echo "  frontend   Start Digital Twin React frontend"
    echo "  stop       Stop all containers and background services"
    echo "  install    Install Python dependencies"
    echo "  help       Show this help message"
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

case "${1:-full}" in
    full)
        start_infra
        start_services
        ;;
    infra)
        start_infra
        ;;
    services)
        start_services
        ;;
    tests)
        run_tests
        ;;
    frontend)
        start_frontend
        ;;
    stop)
        stop_infra
        pkill -f "uvicorn.*railos" 2>/dev/null || true
        log "All stopped."
        ;;
    install)
        install_deps
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        err "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
