"""
RailOS Edge Node Model Weight Store (Task 5.4)
NVMe-backed non-volatile model store. Cold-restart capable — no central connectivity needed.
Satisfies: Req 2 C4, Design §5.2
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MODEL_STORE_PATH = os.environ.get("MODEL_STORE_PATH", "/data/models")
INDEX_FILE       = "model_store.json"


class ModelNotFoundError(FileNotFoundError):
    pass


class ModelStore:
    def __init__(self, store_path: str = MODEL_STORE_PATH) -> None:
        self._root  = Path(store_path)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, str] = self._load_index()

    # ── Public API ─────────────────────────────────────────────────────────────

    def save_model(self, model_id: str, version: str, weights_path: str) -> Path:
        """Copy model weights to the store under model_id/version/.

        Returns the destination path.
        """
        dest_dir = self._root / model_id / version
        dest_dir.mkdir(parents=True, exist_ok=True)
        src  = Path(weights_path)
        dest = dest_dir / src.name
        shutil.copy2(str(src), str(dest))
        self._index[model_id] = version
        self._save_index()
        log.info("Model saved: model_id=%s version=%s path=%s", model_id, version, dest)
        return dest

    def load_model(self, model_id: str) -> Path:
        """Return path to the latest version weights for model_id.

        Raises ModelNotFoundError if no model is stored.
        """
        version = self._index.get(model_id)
        if not version:
            raise ModelNotFoundError(
                f"No model stored for model_id='{model_id}'"
            )
        model_dir = self._root / model_id / version
        # Return the first file in the directory (weights file)
        files = list(model_dir.glob("*"))
        if not files:
            raise ModelNotFoundError(
                f"Model directory exists but contains no files: {model_dir}"
            )
        return files[0]

    def list_models(self) -> dict[str, str]:
        """Return {model_id: version} for all stored models."""
        return dict(self._index)

    def model_version(self, model_id: str) -> Optional[str]:
        return self._index.get(model_id)

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_index(self) -> dict[str, str]:
        index_path = self._root / INDEX_FILE
        if index_path.exists():
            try:
                return json.loads(index_path.read_text())
            except Exception as exc:
                log.warning("Could not read model index: %s — starting fresh", exc)
        return {}

    def _save_index(self) -> None:
        index_path = self._root / INDEX_FILE
        index_path.write_text(json.dumps(self._index, indent=2))
