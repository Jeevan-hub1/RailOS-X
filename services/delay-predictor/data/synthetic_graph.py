"""Synthetic corridor graph generator for testing (Task 8.1)."""
from __future__ import annotations
import random
from .graph_builder import build_corridor_graph


def make_synthetic_graph(n_trains: int = 50, n_stations: int = 20, n_segments: int = 100):
    """Generate a random but structurally valid corridor HeteroData graph."""
    rng = random.Random(42)

    stations = [
        {"stationId": f"S{i}", "platform_count": rng.randint(1, 4),
         "current_occupancy": rng.randint(0, 2),
         "connectedSegments": [f"SEG{rng.randint(0, n_segments-1)}"]}
        for i in range(n_stations)
    ]
    segments = [
        {"segmentId": f"SEG{i}", "length_km": rng.uniform(0.5, 10.0),
         "speed_limit": rng.choice([60, 80, 100, 120, 160]),
         "current_occupancy": rng.randint(0, 2)}
        for i in range(n_segments)
    ]
    trains = [
        {"trainId": f"T{i}",
         "current_delay_min": rng.uniform(-2.0, 30.0),
         "load_factor": rng.uniform(0.2, 1.0),
         "schedule_adherence": rng.uniform(0.5, 1.0),
         "stationId": f"S{rng.randint(0, n_stations-1)}",
         "segmentId": f"SEG{rng.randint(0, n_segments-1)}"}
        for i in range(n_trains)
    ]
    return build_corridor_graph(trains, stations, segments)
