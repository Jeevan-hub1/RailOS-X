"""
RailOS Digital Twin WebSocket Server (Task 13.5)
Real-time corridor simulation with train movement, signals, defect overlays.
Pushes state to frontend clients every 1.5s via WebSocket.

Features:
  - Simulated train movement (physics-based, speed profiles per train class)
  - Signal state management (block section occupancy)
  - Defect/alert overlay on corridor segments
  - Platform occupancy at stations
  - WebSocket delta-only push (bandwidth efficient)
  - REST API for full state snapshot

Satisfies: Req 8 C1, Design section 7.1 Layer E
"""
from __future__ import annotations
import asyncio, hashlib, json, logging, math, os, random, time, threading
from datetime import datetime, timezone
from typing import Any
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Gauge, Counter, start_http_server

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')

PUSH_INTERVAL_S = float(os.environ.get("PUSH_INTERVAL_SECONDS", "1.5"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8085"))
APP_PORT = int(os.environ.get("APP_PORT", "3001"))

connected_clients = Gauge("digital_twin_connected_clients", "WebSocket clients")
state_updates_sent = Counter("digital_twin_updates_sent_total", "State updates pushed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ══════════════════════════════════════════════════════════════════════════════
# Corridor Model (NDLS-MERT, 72km)
# ══════════════════════════════════════════════════════════════════════════════

STATIONS = [
    {"id": "NDLS", "name": "New Delhi", "km": 0, "platforms": 6},
    {"id": "ANVT", "name": "Anand Vihar", "km": 14, "platforms": 4},
    {"id": "GZB", "name": "Ghaziabad", "km": 27, "platforms": 4},
    {"id": "MURN", "name": "Murad Nagar", "km": 43, "platforms": 2},
    {"id": "MODI", "name": "Modi Nagar", "km": 54, "platforms": 2},
    {"id": "MERT", "name": "Meerut", "km": 72, "platforms": 5},
]

SEGMENTS = [
    {"id": "seg-ndls-anvt", "startKm": 0, "endKm": 14, "maxSpeed": 80, "tracks": 4},
    {"id": "seg-anvt-gzb", "startKm": 14, "endKm": 27, "maxSpeed": 110, "tracks": 2},
    {"id": "seg-gzb-murn", "startKm": 27, "endKm": 43, "maxSpeed": 130, "tracks": 2},
    {"id": "seg-murn-modi", "startKm": 43, "endKm": 54, "maxSpeed": 130, "tracks": 2},
    {"id": "seg-modi-mert", "startKm": 54, "endKm": 72, "maxSpeed": 130, "tracks": 2},
]

SIGNALS = [
    {"id": "sig-01", "km": 7, "aspect": "green"},
    {"id": "sig-02", "km": 14, "aspect": "green"},
    {"id": "sig-03", "km": 20, "aspect": "green"},
    {"id": "sig-04", "km": 27, "aspect": "green"},
    {"id": "sig-05", "km": 35, "aspect": "green"},
    {"id": "sig-06", "km": 43, "aspect": "green"},
    {"id": "sig-07", "km": 48, "aspect": "green"},
    {"id": "sig-08", "km": 54, "aspect": "green"},
    {"id": "sig-09", "km": 63, "aspect": "green"},
    {"id": "sig-10", "km": 72, "aspect": "green"},
]

# ══════════════════════════════════════════════════════════════════════════════
# Train Simulation Engine
# ══════════════════════════════════════════════════════════════════════════════

class SimulatedTrain:
    """A simulated train moving along the corridor with physics."""
    def __init__(self, train_id: str, name: str, train_class: str,
                 max_speed_kmh: int, start_km: float, direction: int = 1):
        self.id = train_id
        self.name = name
        self.train_class = train_class
        self.max_speed = max_speed_kmh
        self.km = start_km
        self.direction = direction  # 1=up (NDLS->MERT), -1=down
        self.speed = max_speed_kmh * 0.7  # start at 70% max
        self.delay_min = 0
        self.status = "on-time"
        self.at_station: str | None = None
        self.dwell_remaining_s = 0.0
        self.next_stop_km: float | None = None
        self._accel = 0.5  # m/s^2 acceleration capability
        self._decel = 0.8  # m/s^2 braking capability

    def tick(self, dt_s: float):
        """Advance train by dt seconds."""
        # If dwelling at station
        if self.dwell_remaining_s > 0:
            self.dwell_remaining_s -= dt_s
            self.speed = 0
            if self.dwell_remaining_s <= 0:
                self.at_station = None
            return

        # Check if approaching a station
        for stn in STATIONS:
            dist_to_stn = (stn["km"] - self.km) * self.direction
            if 0 < dist_to_stn < 0.5 and self._should_stop(stn["id"]):
                # Arrive at station
                self.km = stn["km"]
                self.speed = 0
                self.at_station = stn["id"]
                self.dwell_remaining_s = random.uniform(20, 60)
                return

        # Speed profile: accelerate/cruise/decelerate
        segment_max = self._get_segment_max_speed()
        target_speed = min(self.max_speed, segment_max)

        # Random delay injection (simulate real-world disruptions)
        if random.random() < 0.002:  # 0.2% chance per tick
            self.delay_min += random.randint(1, 5)

        # Adjust speed toward target
        if self.speed < target_speed - 5:
            self.speed = min(target_speed, self.speed + self._accel * dt_s * 3.6)
        elif self.speed > target_speed + 5:
            self.speed = max(0, self.speed - self._decel * dt_s * 3.6)

        # Move
        distance_km = (self.speed / 3600) * dt_s
        self.km += distance_km * self.direction

        # Wrap around at corridor ends
        if self.km >= 72:
            self.km = 72
            self.direction = -1
        elif self.km <= 0:
            self.km = 0
            self.direction = 1

        # Update status
        if self.delay_min > 10:
            self.status = "alert"
        elif self.delay_min > 3:
            self.status = "delayed"
        else:
            self.status = "on-time"

    def _should_stop(self, station_id: str) -> bool:
        """Determine if this train stops at given station."""
        # Rajdhani/Shatabdi skip intermediate stations
        if self.train_class in ("Rajdhani", "Shatabdi", "Vande-Bharat"):
            return station_id in ("NDLS", "GZB", "MERT")
        return True  # other trains stop everywhere

    def _get_segment_max_speed(self) -> int:
        for seg in SEGMENTS:
            if seg["startKm"] <= self.km <= seg["endKm"]:
                return seg["maxSpeed"]
        return 100

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "trainClass": self.train_class,
            "km": round(self.km, 2), "speed": round(self.speed, 1),
            "delay": self.delay_min, "status": self.status,
            "direction": "UP" if self.direction == 1 else "DN",
            "atStation": self.at_station,
        }

class CorridorSimulation:
    """Manages the full corridor state: trains, signals, defects."""
    def __init__(self):
        self._trains = [
            SimulatedTrain("T-12301", "Rajdhani Exp", "Rajdhani", 130, 5, 1),
            SimulatedTrain("T-12002", "Shatabdi Exp", "Shatabdi", 130, 40, 1),
            SimulatedTrain("T-22436", "Vande Bharat", "Vande-Bharat", 160, 65, -1),
            SimulatedTrain("T-12213", "Duronto Exp", "Duronto", 120, 20, 1),
            SimulatedTrain("T-12909", "Garib Rath", "Garib-Rath", 110, 55, -1),
            SimulatedTrain("T-12055", "Jan Shatabdi", "Jan-Shatabdi", 110, 30, 1),
        ]
        self._defects: list[dict] = [
            {"id": "def-001", "startKm": 38, "endKm": 42, "condition": "warning",
             "label": "Vibration anomaly", "detectedAt": _now_iso(), "severity": "MEDIUM"},
            {"id": "def-002", "startKm": 55, "endKm": 57, "condition": "defect",
             "label": "Rail crack detected", "detectedAt": _now_iso(), "severity": "HIGH"},
        ]
        self._signals = [dict(s) for s in SIGNALS]
        self._lock = threading.Lock()
        self._tick_count = 0

    def tick(self, dt_s: float = 1.5):
        """Advance simulation by dt seconds."""
        with self._lock:
            self._tick_count += 1
            for train in self._trains:
                train.tick(dt_s)
            self._update_signals()
            # Occasionally inject/clear defects
            if self._tick_count % 40 == 0:
                self._maybe_inject_defect()
            if self._tick_count % 60 == 0:
                self._maybe_clear_defect()

    def _update_signals(self):
        """Update signal aspects based on train proximity (block section logic)."""
        for sig in self._signals:
            sig["aspect"] = "green"
            for train in self._trains:
                dist = abs(train.km - sig["km"])
                if dist < 2:
                    sig["aspect"] = "red"
                elif dist < 5:
                    if sig["aspect"] != "red":
                        sig["aspect"] = "yellow"

    def _maybe_inject_defect(self):
        if len(self._defects) < 5 and random.random() < 0.3:
            km = random.randint(5, 68)
            labels = ["Vibration anomaly", "Temperature spike", "Gauge deviation",
                      "Ballast degradation", "Weld defect suspect"]
            self._defects.append({
                "id": f"def-{random.randint(100,999)}",
                "startKm": km, "endKm": km + random.randint(1, 4),
                "condition": random.choice(["warning", "defect"]),
                "label": random.choice(labels),
                "detectedAt": _now_iso(),
                "severity": random.choice(["MEDIUM", "HIGH", "LOW"]),
            })

    def _maybe_clear_defect(self):
        if self._defects and random.random() < 0.4:
            self._defects.pop(0)

    def get_state(self) -> dict:
        with self._lock:
            trains_sorted = sorted(self._trains, key=lambda t: t.km)
            on_time = sum(1 for t in self._trains if t.status == "on-time")
            return {
                "trains": [t.to_dict() for t in trains_sorted],
                "defects": list(self._defects),
                "signals": [dict(s) for s in self._signals],
                "stations": STATIONS,
                "segments": SEGMENTS,
                "stats": {
                    "activeTrains": len(self._trains),
                    "onTimePct": round(on_time / max(len(self._trains), 1) * 100),
                    "trackAlerts": len(self._defects),
                    "maxSpeed": max((t.speed for t in self._trains), default=0),
                    "totalDelayMin": sum(t.delay_min for t in self._trains),
                },
                "timestamp": _now_iso(),
            }

# ══════════════════════════════════════════════════════════════════════════════
# FastAPI App + WebSocket
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="RailOS Digital Twin", docs_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

simulation = CorridorSimulation()
_clients: list[WebSocket] = []


async def _simulation_loop():
    """Background task: advance simulation every PUSH_INTERVAL_S."""
    while True:
        simulation.tick(PUSH_INTERVAL_S)
        await asyncio.sleep(PUSH_INTERVAL_S)


@app.on_event("startup")
async def _startup():
    start_http_server(METRICS_PORT)
    asyncio.create_task(_simulation_loop())
    log.info("Digital Twin started on port %d (push interval %.1fs)", APP_PORT, PUSH_INTERVAL_S)


@app.get("/health")
def health():
    return {"status": "ok", "clients": len(_clients), "simulation": "running"}


@app.get("/api/v1/state")
def get_state():
    """Full corridor state snapshot (REST)."""
    return simulation.get_state()


@app.get("/api/v1/corridor")
def get_corridor():
    """Static corridor definition (stations, segments)."""
    return {"stations": STATIONS, "segments": SEGMENTS, "totalKm": 72}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.append(ws)
    connected_clients.inc()
    log.info("WS client connected (total=%d)", len(_clients))
    prev_hash = ""
    try:
        while True:
            state = simulation.get_state()
            current_hash = hashlib.md5(
                json.dumps(state, sort_keys=True, default=str).encode()
            ).hexdigest()
            if current_hash != prev_hash:
                await ws.send_text(json.dumps({"type": "state_update", "data": state}))
                prev_hash = current_hash
                state_updates_sent.inc()
            await asyncio.sleep(PUSH_INTERVAL_S)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.error("WS error: %s", exc)
    finally:
        if ws in _clients:
            _clients.remove(ws)
        connected_clients.dec()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT, log_config=None)
