#!/usr/bin/env python3
"""
RailOS-X — Start all core services in a single process for local development.
Uses uvicorn to mount each service on a different port via multiprocessing.
"""
import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
os.environ.setdefault("DB_URL", "postgresql://railos:railos-dev@localhost:5432/railos")


def start_kavach():
    import uvicorn
    from services.kavach_advisory.kavach_advisory import app
    uvicorn.run(app, host="0.0.0.0", port=8082, log_level="info")


def start_authgate():
    import uvicorn
    from services.authorization_gate.gate_service import app
    uvicorn.run(app, host="0.0.0.0", port=8087, log_level="info")


def start_marl():
    import uvicorn
    from services.marl_scheduler.service.scheduler_service import app
    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="info")


if __name__ == "__main__":
    print("=" * 70)
    print("RailOS-X — Starting Core Services")
    print("=" * 70)
    print()
    print("  Kavach++ Advisory:    http://localhost:8082")
    print("  Authorization Gate:   http://localhost:8087")
    print("  MARL Scheduler:       http://localhost:8081")
    print()
    print("=" * 70)

    procs = [
        multiprocessing.Process(target=start_kavach, name="kavach-advisory"),
        multiprocessing.Process(target=start_authgate, name="auth-gate"),
        multiprocessing.Process(target=start_marl, name="marl-scheduler"),
    ]

    for p in procs:
        p.start()
        print(f"  Started {p.name} (PID {p.pid})")

    print()
    print("All services started. Press Ctrl+C to stop.")

    try:
        for p in procs:
            p.join()
    except KeyboardInterrupt:
        print("\nShutting down...")
        for p in procs:
            p.terminate()
        for p in procs:
            p.join(timeout=5)
        print("All services stopped.")
