"""
Tests for ModelStore (Task 5.6)
Covers: save/load round-trip, cold-restart simulation, ModelNotFoundError,
        and version ordering.
Satisfies: Req 2 C4
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Allow imports from parent services/edge-node directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from model_store.model_store import ModelStore, ModelNotFoundError


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_weights_file(tmp_path: Path, filename: str = "weights.pt",
                       content: bytes = b"fake-weights") -> Path:
    weights = tmp_path / filename
    weights.write_bytes(content)
    return weights


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestSaveLoadRoundTrip:
    """save_model followed by load_model returns the stored weights file."""

    def test_save_then_load_returns_valid_path(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))
        weights = _make_weights_file(tmp_path)

        saved_path = store.save_model("vibration-classifier", "v1.0", str(weights))
        loaded_path = store.load_model("vibration-classifier")

        assert saved_path == loaded_path
        assert loaded_path.exists()

    def test_loaded_file_content_matches_original(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))
        original_content = b"\x00\x01\x02\x03pytorch-weights"
        weights = _make_weights_file(tmp_path, content=original_content)

        store.save_model("speed-predictor", "v2.1", str(weights))
        loaded_path = store.load_model("speed-predictor")

        assert loaded_path.read_bytes() == original_content

    def test_list_models_reflects_saved(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))
        weights = _make_weights_file(tmp_path)

        store.save_model("model-a", "v1.0", str(weights))
        store.save_model("model-b", "v3.0", str(weights))

        listing = store.list_models()
        assert listing == {"model-a": "v1.0", "model-b": "v3.0"}


class TestColdRestart:
    """Index survives process restart — new ModelStore from same path can load."""

    def test_cold_restart_load_succeeds(self, tmp_path: Path) -> None:
        store_path = str(tmp_path / "models")
        weights = _make_weights_file(tmp_path)

        # First process: save model
        store1 = ModelStore(store_path=store_path)
        store1.save_model("track-monitor", "v1.2", str(weights))

        # Second process (cold restart): create new ModelStore from same path
        store2 = ModelStore(store_path=store_path)
        loaded_path = store2.load_model("track-monitor")

        assert loaded_path.exists()
        assert loaded_path.read_bytes() == weights.read_bytes()

    def test_cold_restart_index_persists_multiple_models(self, tmp_path: Path) -> None:
        store_path = str(tmp_path / "models")
        weights = _make_weights_file(tmp_path)

        store1 = ModelStore(store_path=store_path)
        store1.save_model("model-x", "v1.0", str(weights))
        store1.save_model("model-y", "v2.5", str(weights))

        # Simulate restart
        store2 = ModelStore(store_path=store_path)
        assert store2.model_version("model-x") == "v1.0"
        assert store2.model_version("model-y") == "v2.5"

    def test_empty_store_on_fresh_path(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "fresh-models"))
        assert store.list_models() == {}


class TestModelNotFoundError:
    """load_model raises ModelNotFoundError for unknown model_id."""

    def test_raises_on_unknown_model_id(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))

        with pytest.raises(ModelNotFoundError):
            store.load_model("nonexistent-model")

    def test_raises_specific_model_id_in_message(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))

        with pytest.raises(ModelNotFoundError, match="unknown-model-xyz"):
            store.load_model("unknown-model-xyz")

    def test_error_is_subclass_of_file_not_found(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))

        with pytest.raises(FileNotFoundError):
            store.load_model("any-model")


class TestVersionOrdering:
    """Saving a new version for the same model_id updates the latest pointer."""

    def test_latest_version_updated_on_resave(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))

        v1_weights = _make_weights_file(tmp_path, "weights_v1.pt", b"v1-data")
        v2_weights = _make_weights_file(tmp_path, "weights_v2.pt", b"v2-data")

        store.save_model("classifier", "v1.0", str(v1_weights))
        assert store.model_version("classifier") == "v1.0"

        store.save_model("classifier", "v2.0", str(v2_weights))
        assert store.model_version("classifier") == "v2.0"

    def test_load_after_version_upgrade_returns_new_weights(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))

        v1 = _make_weights_file(tmp_path, "w1.pt", b"version-one")
        v2 = _make_weights_file(tmp_path, "w2.pt", b"version-two")

        store.save_model("detector", "v1.0", str(v1))
        store.save_model("detector", "v2.0", str(v2))

        loaded = store.load_model("detector")
        assert loaded.read_bytes() == b"version-two"

    def test_multiple_distinct_models_independent_versions(self, tmp_path: Path) -> None:
        store = ModelStore(store_path=str(tmp_path / "models"))

        wa = _make_weights_file(tmp_path, "a.pt", b"model-a")
        wb = _make_weights_file(tmp_path, "b.pt", b"model-b")

        store.save_model("model-alpha", "v1.0", str(wa))
        store.save_model("model-beta",  "v3.0", str(wb))

        assert store.model_version("model-alpha") == "v1.0"
        assert store.model_version("model-beta")  == "v3.0"
