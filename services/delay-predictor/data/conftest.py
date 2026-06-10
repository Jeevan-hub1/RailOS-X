"""
conftest.py — pytest fixtures for the GNN Delay Predictor data layer.

Provides ``synthetic_hetero_data`` fixture used across all test modules.
"""

import pytest
from torch_geometric.data import HeteroData

from .synthetic_graph import build_synthetic_hetero_data


@pytest.fixture(scope="session")
def synthetic_hetero_data() -> HeteroData:
    """Return a ready HeteroData object (20 stations, 50 trains, 100 segments).

    Session-scoped: built once and shared across the full test run for speed.
    """
    return build_synthetic_hetero_data(
        n_stations=20,
        n_trains=50,
        n_segments=100,
        seed=42,
    )
