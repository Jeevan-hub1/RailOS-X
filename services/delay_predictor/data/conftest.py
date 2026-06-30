"""
conftest.py — pytest fixtures for the GNN Delay Predictor data layer.

Provides ``synthetic_hetero_data`` fixture used across all test modules.
"""

import pytest


@pytest.fixture(scope="session")
def synthetic_hetero_data():
    """Return a ready HeteroData object (20 stations, 50 trains, 100 segments).

    Session-scoped: built once and shared across the full test run for speed.
    Skips gracefully when the optional ``torch_geometric`` dependency is absent
    so that test collection never fails on its account.
    """
    pytest.importorskip("torch_geometric")
    from services.delay_predictor.data.synthetic_graph import build_synthetic_hetero_data

    return build_synthetic_hetero_data(
        n_stations=20,
        n_trains=50,
        n_segments=100,
        seed=42,
    )
