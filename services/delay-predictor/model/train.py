"""
train.py — Task 8.2
Training script for HetGNN-SAGE delay predictor.

MLflow logging:
  - railos_model_version  (e.g. "1.0.0")
  - railos_requirement_id = "REQ-005"
  - Artifacts: trained model state dict, calibration residuals

Usage
-----
    python -m services.delay_predictor.model.train \
        --epochs 50 \
        --lr 1e-3 \
        --hidden 128 \
        --model-version 1.0.0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import mlflow
import numpy as np
import torch
import torch.nn as nn
from torch_geometric.data import HeteroData

# Allow running as `python train.py` from inside model/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services.delay_predictor.data.synthetic_graph import make_synthetic_graph
from services.delay_predictor.model.conformal_predictor import ConformalDelayPredictor
from services.delay_predictor.model.hetgnn_model import HetGNN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REQUIREMENT_ID = "REQ-005"
EXPERIMENT_NAME = "railos_delay_predictor"


# ---------------------------------------------------------------------------
# Synthetic dataset generation
# ---------------------------------------------------------------------------

def _make_dataset(
    n_graphs: int = 200,
    n_trains: int = 30,
    n_stations: int = 10,
    n_segments: int = 40,
) -> List[Tuple[HeteroData, Dict[int, float]]]:
    """Create synthetic (graph, true_delays) pairs for training / evaluation."""
    dataset = []
    for i in range(n_graphs):
        g = make_synthetic_graph(
            n_trains=n_trains,
            n_stations=n_stations,
            n_segments=n_segments,
            seed=i,
        )
        # Ground-truth: random delays correlated with current_delay_min feature
        true_delays: Dict[int, float] = {}
        for j in range(g["train"].x.shape[0]):
            base_delay = g["train"].x[j, 0].item()  # current_delay_min
            noise = float(np.random.default_rng(i * 1000 + j).normal(0, 2))
            true_delays[j] = max(0.0, base_delay + noise)
        dataset.append((g, true_delays))
    return dataset


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train(
    model_version: str = "1.0.0",
    hidden_dim: int = 128,
    epochs: int = 20,
    lr: float = 1e-3,
    train_graphs: int = 160,
    cal_graphs: int = 20,
    test_graphs: int = 20,
    output_dir: str = "artifacts",
) -> None:
    """Train HetGNN and calibrate ConformalDelayPredictor; log to MLflow."""

    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(tags={"railos_requirement_id": REQUIREMENT_ID}):
        mlflow.log_params(
            {
                "railos_model_version": model_version,
                "hidden_dim": hidden_dim,
                "epochs": epochs,
                "lr": lr,
            }
        )

        # ---- Dataset --------------------------------------------------------
        log.info("Generating synthetic dataset …")
        total_graphs = train_graphs + cal_graphs + test_graphs
        all_data = _make_dataset(n_graphs=total_graphs)
        train_data = all_data[:train_graphs]
        cal_data = all_data[train_graphs: train_graphs + cal_graphs]
        test_data = all_data[train_graphs + cal_graphs:]

        # ---- Model ----------------------------------------------------------
        model = HetGNN(hidden_dim=hidden_dim)
        optimiser = torch.optim.Adam(model.parameters(), lr=lr)
        criterion = nn.MSELoss()

        # ---- Training loop --------------------------------------------------
        model.train()
        for epoch in range(1, epochs + 1):
            total_loss = 0.0
            for g, true_delays in train_data:
                optimiser.zero_grad()
                preds = model(
                    {nt: g[nt].x for nt in ["train", "station", "segment"]
                     if hasattr(g[nt], "x") and g[nt].x is not None},
                    {et: g[et].edge_index
                     for et in [
                         ("train", "train_to_station", "station"),
                         ("station", "station_to_segment", "segment"),
                         ("train", "train_to_train", "train"),
                     ]
                     if hasattr(g[et], "edge_index") and g[et].edge_index is not None},
                )  # (n_trains,)

                n = preds.shape[0]
                if n == 0:
                    continue
                y = torch.tensor(
                    [true_delays[j] for j in range(n)],
                    dtype=torch.float32,
                )
                loss = criterion(preds, y)
                loss.backward()
                optimiser.step()
                total_loss += loss.item()

            avg_loss = total_loss / max(len(train_data), 1)
            log.info("Epoch %d/%d — train MSE: %.4f", epoch, epochs, avg_loss)
            mlflow.log_metric("train_mse", avg_loss, step=epoch)

        # ---- Conformal calibration ------------------------------------------
        log.info("Calibrating conformal predictor …")
        predictor = ConformalDelayPredictor(model)
        predictor.calibrate(cal_data)
        mlflow.log_metric("calibration_half_width", predictor._half_width)

        # ---- Test evaluation ------------------------------------------------
        model.eval()
        all_abs_errors: List[float] = []
        with torch.no_grad():
            for g, true_delays in test_data:
                preds_dict = model.predict(g)
                for idx, y_true in true_delays.items():
                    y_pred = preds_dict.get(idx, 0.0)
                    all_abs_errors.append(abs(y_true - y_pred))

        mae = float(np.mean(all_abs_errors)) if all_abs_errors else 0.0
        log.info("Test MAE: %.4f minutes", mae)
        mlflow.log_metric("test_mae", mae)

        # ---- Artifacts ------------------------------------------------------
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        model_path = os.path.join(output_dir, "hetgnn_model.pt")
        torch.save(model.state_dict(), model_path)

        residuals_path = os.path.join(output_dir, "cal_residuals.json")
        with open(residuals_path, "w") as fh:
            json.dump(predictor.get_residuals(), fh)

        mlflow.log_artifact(model_path)
        mlflow.log_artifact(residuals_path)
        mlflow.log_param("railos_model_version", model_version)
        mlflow.set_tag("railos_model_version", model_version)
        log.info("Training complete. Artifacts saved to %s", output_dir)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train HetGNN-SAGE delay predictor."
    )
    parser.add_argument("--model-version", default="1.0.0")
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--output-dir", default="artifacts")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    train(
        model_version=args.model_version,
        hidden_dim=args.hidden,
        epochs=args.epochs,
        lr=args.lr,
        output_dir=args.output_dir,
    )
