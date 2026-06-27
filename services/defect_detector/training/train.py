"""
RailOS Defect Detector — YOLOv8n Fine-Tuning Script
Requirement: REQ-003 (Track Defect Detection)
MLflow tag: railos_requirement_id=REQ-003

Fine-tunes YOLOv8n (pretrained on COCO) on the IR corridor track defect dataset,
logs all metrics and artifacts to MLflow, saves best checkpoint.

Usage:
    python train.py --data-yaml data/splits/data.yaml
    python train.py --data-yaml data/splits/data.yaml --epochs 50 --batch 8 --device cpu
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Graceful import handling — ultralytics and mlflow may not be installed in
# all environments (e.g., CI lint/test without GPU).
# ---------------------------------------------------------------------------
try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False

try:
    import mlflow
    import mlflow.pytorch
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants (match design §6.1)
# ---------------------------------------------------------------------------
CLASSES = ["crack", "flaking", "fastener_loose", "spalling"]
DEFAULT_EPOCHS = 100
DEFAULT_IMGSZ = 640
DEFAULT_BATCH = 16
DEFAULT_PATIENCE = 20
DEFAULT_PRETRAINED_WEIGHTS = "yolov8n.pt"
MLFLOW_EXPERIMENT_NAME = "railos-defect-detector"
RAILOS_MODEL_VERSION_TAG = "1.0.0"
REQUIREMENT_ID = "REQ-003"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fine-tune YOLOv8n for RailOS track defect detection"
    )
    parser.add_argument(
        "--data-yaml",
        default="data/splits/data.yaml",
        help="Path to YOLO data.yaml file",
    )
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--imgsz", type=int, default=DEFAULT_IMGSZ)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--patience", type=int, default=DEFAULT_PATIENCE)
    parser.add_argument(
        "--weights",
        default=DEFAULT_PRETRAINED_WEIGHTS,
        help="Pretrained weights path or model name",
    )
    parser.add_argument(
        "--device",
        default="0",
        help="Training device: 0 for GPU, 'cpu' for CPU",
    )
    parser.add_argument(
        "--output-dir",
        default="runs/train",
        help="Output directory for training artifacts",
    )
    parser.add_argument(
        "--mlflow-tracking-uri",
        default=os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
        help="MLflow tracking server URI",
    )
    return parser.parse_args()


def setup_mlflow(tracking_uri: str) -> Optional[str]:
    """Configure MLflow tracking and return active run ID, or None if unavailable."""
    if not MLFLOW_AVAILABLE:
        print("[train] WARNING: mlflow not installed — metrics will not be logged.")
        return None

    try:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
        return "configured"
    except Exception as exc:
        print(f"[train] WARNING: MLflow setup failed: {exc}")
        return None


def log_metrics_to_mlflow(run_id: str, results: dict) -> None:
    """Log training metrics extracted from YOLO results to the active MLflow run."""
    if not MLFLOW_AVAILABLE or run_id is None:
        return

    metric_keys = [
        "metrics/precision(B)",
        "metrics/recall(B)",
        "metrics/mAP50(B)",
        "metrics/mAP50-95(B)",
        "train/box_loss",
        "train/cls_loss",
        "val/box_loss",
        "val/cls_loss",
    ]
    for key in metric_keys:
        val = results.results_dict.get(key)
        if val is not None:
            clean_key = key.replace("/", "_").replace("(", "_").replace(")", "")
            mlflow.log_metric(clean_key, float(val))


def train(args: argparse.Namespace) -> Path:
    """
    Main training function.

    1. Loads YOLOv8n pretrained on COCO.
    2. Fine-tunes on the IR defect dataset.
    3. Logs hyperparams, metrics, and the best checkpoint to MLflow.
    4. Returns path to the best model checkpoint.

    Raises:
        RuntimeError: If ultralytics is not available.
        FileNotFoundError: If the data YAML file does not exist.
    """
    if not ULTRALYTICS_AVAILABLE:
        raise RuntimeError(
            "ultralytics package is required for training. "
            "Install with: pip install ultralytics==8.2.0"
        )

    data_yaml = Path(args.data_yaml)
    if not data_yaml.exists():
        raise FileNotFoundError(
            f"Data YAML not found: {data_yaml}. "
            "Run prepare_dataset.py first to generate splits."
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mlflow_ok = setup_mlflow(args.mlflow_tracking_uri)

    # Start MLflow run
    run_context = (
        mlflow.start_run(
            tags={
                "railos_model_version": RAILOS_MODEL_VERSION_TAG,
                "railos_requirement_id": REQUIREMENT_ID,
                "model_architecture": "yolov8n",
                "quantization": "none",  # pre-export
            }
        )
        if MLFLOW_AVAILABLE and mlflow_ok
        else _NullContext()
    )

    with run_context as run:
        # Log hyperparameters
        hyperparams = {
            "epochs": args.epochs,
            "imgsz": args.imgsz,
            "batch": args.batch,
            "patience": args.patience,
            "weights": args.weights,
            "device": args.device,
            "classes": CLASSES,
            "num_classes": len(CLASSES),
        }
        if MLFLOW_AVAILABLE and mlflow_ok:
            mlflow.log_params(hyperparams)

        print(f"[train] Loading pretrained weights: {args.weights}")
        model = YOLO(args.weights)

        print(f"[train] Starting fine-tuning on: {data_yaml}")
        print(f"[train] Hyperparameters: {json.dumps(hyperparams, indent=2)}")

        results = model.train(
            data=str(data_yaml),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            patience=args.patience,
            device=args.device,
            project=str(output_dir),
            name="defect_detector",
            save=True,
            plots=True,
            exist_ok=True,
        )

        # Log final metrics to MLflow
        if MLFLOW_AVAILABLE and mlflow_ok:
            log_metrics_to_mlflow(getattr(run, "info", {}).get("run_id", ""), results)

            # Save checkpoint as MLflow artifact
            best_ckpt = output_dir / "defect_detector" / "weights" / "best.pt"
            if best_ckpt.exists():
                mlflow.log_artifact(str(best_ckpt), artifact_path="model_checkpoints")
                print(f"[train] Best checkpoint logged to MLflow: {best_ckpt}")

            # Log training plots
            plots_dir = output_dir / "defect_detector"
            for plot in plots_dir.glob("*.png"):
                mlflow.log_artifact(str(plot), artifact_path="plots")

        print("[train] Training complete.")
        best_ckpt_path = output_dir / "defect_detector" / "weights" / "best.pt"
        print(f"[train] Best checkpoint: {best_ckpt_path}")
        return best_ckpt_path


class _NullContext:
    """No-op context manager for when MLflow is unavailable."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


if __name__ == "__main__":
    args = parse_args()
    best_ckpt = train(args)
    print(f"[train] Best model checkpoint saved to: {best_ckpt}")
