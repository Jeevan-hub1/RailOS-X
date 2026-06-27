"""
RailOS GNN Delay Predictor — Graph Builder (Task 8.1)
Builds heterogeneous corridor graph for HetGNN-SAGE inference.
Satisfies: Req 5 C2, Design §6.3
"""
from __future__ import annotations

from typing import Any
import torch

try:
    from torch_geometric.data import HeteroData
    _PYG_AVAILABLE = True
except ImportError:
    _PYG_AVAILABLE = False
    HeteroData = dict  # type: ignore


def build_corridor_graph(
    trains:   list[dict[str, Any]],
    stations: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> Any:
    """Build a HeteroData graph from corridor snapshot dicts.

    Node features:
      Train:   [current_delay_min, load_factor, schedule_adherence]       (3)
      Station: [platform_count, current_occupancy]                         (2)
      Segment: [length_km, speed_limit, current_occupancy]                 (3)

    Edge types:
      (train, occupies, station)   — train occupies its current station
      (station, connects, segment) — station is at one end of a segment
      (train, headway, train)      — consecutive trains on same segment
    """
    # ── Node features ────────────────────────────────────────────────────────
    train_x = torch.tensor(
        [[float(t.get("current_delay_min", 0)),
          float(t.get("load_factor", 0.5)),
          float(t.get("schedule_adherence", 1.0))]
         for t in trains], dtype=torch.float
    ) if trains else torch.zeros((0, 3))

    station_x = torch.tensor(
        [[float(s.get("platform_count", 1)),
          float(s.get("current_occupancy", 0))]
         for s in stations], dtype=torch.float
    ) if stations else torch.zeros((0, 2))

    segment_x = torch.tensor(
        [[float(sg.get("length_km", 1.0)),
          float(sg.get("speed_limit", 100)),
          float(sg.get("current_occupancy", 0))]
         for sg in segments], dtype=torch.float
    ) if segments else torch.zeros((0, 3))

    # ── Build index maps ──────────────────────────────────────────────────────
    train_id_to_idx   = {t.get("trainId",   str(i)): i for i, t  in enumerate(trains)}
    station_id_to_idx = {s.get("stationId", str(i)): i for i, s  in enumerate(stations)}
    segment_id_to_idx = {sg.get("segmentId",str(i)): i for i, sg in enumerate(segments)}

    # ── Train → Station edges ─────────────────────────────────────────────────
    ts_src, ts_dst = [], []
    for t_idx, t in enumerate(trains):
        sid = t.get("stationId")
        if sid and sid in station_id_to_idx:
            ts_src.append(t_idx)
            ts_dst.append(station_id_to_idx[sid])

    # ── Station → Segment edges ───────────────────────────────────────────────
    ss_src, ss_dst = [], []
    for st_idx, s in enumerate(stations):
        for seg_id in s.get("connectedSegments", []):
            if seg_id in segment_id_to_idx:
                ss_src.append(st_idx)
                ss_dst.append(segment_id_to_idx[seg_id])

    # ── Train → Train headway edges ───────────────────────────────────────────
    # Pair consecutive trains sharing the same segment
    seg_trains: dict[str, list[int]] = {}
    for t_idx, t in enumerate(trains):
        seg = t.get("segmentId", "")
        if seg:
            seg_trains.setdefault(seg, []).append(t_idx)

    tt_src, tt_dst = [], []
    for t_list in seg_trains.values():
        for i in range(len(t_list) - 1):
            tt_src.append(t_list[i])
            tt_dst.append(t_list[i + 1])

    # ── Assemble HeteroData ───────────────────────────────────────────────────
    if _PYG_AVAILABLE:
        data = HeteroData()
        data["train"].x   = train_x
        data["station"].x = station_x
        data["segment"].x = segment_x

        data["train",   "occupies", "station"].edge_index = _edge_index(ts_src, ts_dst)
        data["station", "connects", "segment"].edge_index = _edge_index(ss_src, ss_dst)
        data["train",   "headway",  "train"].edge_index   = _edge_index(tt_src, tt_dst)
    else:
        # Fallback dict for environments without PyG
        data = {
            "train_x": train_x, "station_x": station_x, "segment_x": segment_x,
            "train_to_station": (ts_src, ts_dst),
            "station_to_segment": (ss_src, ss_dst),
            "train_to_train": (tt_src, tt_dst),
        }
    return data


def _edge_index(src: list[int], dst: list[int]) -> torch.Tensor:
    if not src:
        return torch.zeros((2, 0), dtype=torch.long)
    return torch.tensor([src, dst], dtype=torch.long)
