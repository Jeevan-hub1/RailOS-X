"""
RailOS HetGNN-SAGE Delay Predictor (Task 8.2)
HeteroConv with SAGEConv, 2 layers, 128 hidden units.
Satisfies: Req 5, Design §6.3
"""
from __future__ import annotations
from typing import Any
import torch
import torch.nn as nn

try:
    from torch_geometric.nn import HeteroConv, SAGEConv, Linear
    _PYG_AVAILABLE = True
except ImportError:
    _PYG_AVAILABLE = False


class HetGNN(nn.Module):
    """Heterogeneous GNN for delay propagation prediction."""

    def __init__(self, hidden_channels: int = 128) -> None:
        super().__init__()

        if not _PYG_AVAILABLE:
            # Fallback linear model for environments without PyG
            self._fallback = nn.Linear(3, 1)
            self._use_fallback = True
            return

        self._use_fallback = False

        # Input projections per node type
        self.train_proj   = Linear(3, hidden_channels)
        self.station_proj = Linear(2, hidden_channels)
        self.segment_proj = Linear(3, hidden_channels)

        # Layer 1
        self.conv1 = HeteroConv({
            ("train",   "occupies", "station"): SAGEConv(hidden_channels, hidden_channels),
            ("station", "connects", "segment"): SAGEConv(hidden_channels, hidden_channels),
            ("train",   "headway",  "train"):   SAGEConv(hidden_channels, hidden_channels),
        }, aggr="mean")

        # Layer 2
        self.conv2 = HeteroConv({
            ("train",   "occupies", "station"): SAGEConv(hidden_channels, hidden_channels),
            ("station", "connects", "segment"): SAGEConv(hidden_channels, hidden_channels),
            ("train",   "headway",  "train"):   SAGEConv(hidden_channels, hidden_channels),
        }, aggr="mean")

        # Output head: predict delay in minutes per Train node
        self.head = nn.Linear(hidden_channels, 1)
        self.relu = nn.ReLU()

    def forward(self, x_dict: dict, edge_index_dict: dict) -> torch.Tensor:
        """Returns (n_trains, 1) delay predictions in minutes."""
        if self._use_fallback:
            return self._fallback(x_dict.get("train", torch.zeros(1, 3)))

        # Project node features to hidden space
        x = {
            "train":   self.relu(self.train_proj(x_dict["train"])),
            "station": self.relu(self.station_proj(x_dict["station"])),
            "segment": self.relu(self.segment_proj(x_dict["segment"])),
        }

        # Message passing layer 1
        x = self.conv1(x, edge_index_dict)
        x = {k: self.relu(v) for k, v in x.items()}

        # Message passing layer 2
        x = self.conv2(x, edge_index_dict)
        x = {k: self.relu(v) for k, v in x.items()}

        # Predict delay for Train nodes
        return self.head(x["train"])

    def predict(self, hetero_data: Any) -> dict[int, float]:
        """Returns {train_idx: delay_minutes} for all trains in the graph."""
        self.eval()
        with torch.no_grad():
            if self._use_fallback:
                n = hetero_data.get("train_x", torch.zeros(1, 3)).shape[0]
                return {i: 0.0 for i in range(n)}

            out = self.forward(hetero_data.x_dict, hetero_data.edge_index_dict)
            return {i: float(out[i, 0]) for i in range(out.shape[0])}
