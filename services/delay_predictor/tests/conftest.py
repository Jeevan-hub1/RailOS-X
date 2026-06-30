"""Pytest fixtures for delay-predictor tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from data.synthetic_graph import make_synthetic_graph


@pytest.fixture
def synthetic_graph_fixture():
    return make_synthetic_graph(n_trains=10, n_stations=5, n_segments=20)
