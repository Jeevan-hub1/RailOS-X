"""
pytest conftest for defect-detector data module.
Provides the `synthetic_dataset` fixture that generates a small synthetic
dataset for use in unit and integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from synthetic_generator import generate_synthetic_dataset, CLASSES


@pytest.fixture(scope="session")
def synthetic_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Session-scoped fixture: generates a synthetic dataset with
    DEFAULT_IMAGES_PER_CLASS (100) images per defect class and returns
    the path to the dataset root directory.

    The directory structure is:
        <tmpdir>/
            crack/          (100 PNG images)
            flaking/        (100 PNG images)
            fastener_loose/ (100 PNG images)
            spalling/       (100 PNG images)

    The fixture is session-scoped so the dataset is created only once
    per test session, saving generation time.
    """
    dataset_root = tmp_path_factory.mktemp("synthetic_dataset")
    generate_synthetic_dataset(output_dir=dataset_root, images_per_class=100, seed=42)
    return dataset_root


@pytest.fixture(scope="session")
def synthetic_dataset_small(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Session-scoped fixture: generates a smaller synthetic dataset with
    10 images per defect class for fast unit tests that don't need
    the full 100-image fixture.
    """
    dataset_root = tmp_path_factory.mktemp("synthetic_dataset_small")
    generate_synthetic_dataset(output_dir=dataset_root, images_per_class=10, seed=123)
    return dataset_root
