"""Pytest fixtures for delay-predictor tests."""
import pytest

from services.delay_predictor.data.synthetic_graph import make_synthetic_graph


@pytest.fixture
def synthetic_graph_fixture():
    return make_synthetic_graph(n_trains=10, n_stations=5, n_segments=20)
