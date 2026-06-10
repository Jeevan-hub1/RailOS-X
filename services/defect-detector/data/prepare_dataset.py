"""
RailOS Defect Detector — Dataset Preparation Script
Requirement: REQ-003 (Track Defect Detection)
MLflow tag: railos_requirement_id=REQ-003

Validates dataset structure, generates YOLO-format label files,
creates train/val/test splits, and outputs dataset statistics JSON.
"""

from __future__ import annotations

import json
import os
import random
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

CLASSES = ["crack", "flaking", "fastener_loose", "spalling"]
MIN_IMAGES_PER_CLASS = 500
TRAIN_SPLIT = 0.80
VAL_SPLIT = 0.10
TEST_SPLIT = 0.10
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}


def load_config(config_path: str | Path = "data/dataset_config.yaml") -> dict:
    """Load dataset configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def validate_dataset_structure(raw_dir: Path) -> Dict[str, List[Path]]:
    """
    Validate that the raw dataset directory contains the required class folders
    and that each class meets the minimum image count requirement.

    Args:
        raw_dir: Path to the raw images directory.

    Returns:
        Dict mapping class name → list of image paths.

    Raises:
        FileNotFoundError: If raw_dir does not exist.
        ValueError: If any class folder is missing or has fewer than MIN_IMAGES_PER_CLASS images.
    """
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw dataset directory not found: {raw_dir}")

    class_images: Dict[str, List[Path]] = {}
    errors: List[str] = []

    for cls in CLASSES:
        cls_dir = raw_dir / cls
        if not cls_dir.is_dir():
            errors.append(f"Missing class directory: {cls_dir}")
            continue

        images = [
            p for p in cls_dir.iterdir()
            if p.suffix.lower() in IMAGE_EXTENSIONS
        ]
        class_images[cls] = images

        if len(images) < MIN_IMAGES_PER_CLASS:
            errors.append(
                f"Class '{cls}' has only {len(images)} images "
                f"(minimum required: {MIN_IMAGES_PER_CLASS})"
            )

    if errors:
        raise ValueError(
            "Dataset validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return class_images


def generate_yolo_label(
    class_idx: int,
    cx: float = 0.5,
    cy: float = 0.5,
    w: float = 0.5,
    h: float = 0.4,
) -> str:
    """
    Generate a YOLO format label string.
    Format: <class_idx> <cx> <cy> <width> <height>  (all normalized 0–1)
    """
    return f"{class_idx} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n"


def create_label_files(
    class_images: Dict[str, List[Path]],
    labels_dir: Path,
) -> None:
    """
    Generate YOLO-format .txt label files for every image that does not yet
    have one. Label files are placed in labels_dir/<class>/<stem>.txt.

    For images without existing bounding box annotations (e.g., synthetic data),
    a default centered box covering ~50% of the frame is generated.
    """
    labels_dir.mkdir(parents=True, exist_ok=True)

    for cls_idx, cls in enumerate(CLASSES):
        cls_labels_dir = labels_dir / cls
        cls_labels_dir.mkdir(parents=True, exist_ok=True)

        for img_path in class_images.get(cls, []):
            label_path = cls_labels_dir / (img_path.stem + ".txt")
            if not label_path.exists():
                label_path.write_text(generate_yolo_label(cls_idx))


def create_splits(
    class_images: Dict[str, List[Path]],
    splits_dir: Path,
    labels_dir: Path,
    seed: int = 42,
) -> Dict[str, Dict[str, int]]:
    """
    Create train/val/test splits with stratification per class.
    Each split folder contains symlinks (or copies) of images and labels
    in YOLO dataset directory format.

    Returns a dict of split → {class: count}.
    """
    random.seed(seed)
    splits_dir.mkdir(parents=True, exist_ok=True)

    split_counts: Dict[str, Dict[str, int]] = {
        "train": {},
        "val": {},
        "test": {},
    }

    for split_name in ("train", "val", "test"):
        for sub in ("images", "labels"):
            (splits_dir / split_name / sub).mkdir(parents=True, exist_ok=True)

    for cls_idx, cls in enumerate(CLASSES):
        images = list(class_images[cls])
        random.shuffle(images)

        n = len(images)
        n_train = int(n * TRAIN_SPLIT)
        n_val = int(n * VAL_SPLIT)

        train_imgs = images[:n_train]
        val_imgs = images[n_train : n_train + n_val]
        test_imgs = images[n_train + n_val :]

        for split_name, split_imgs in [
            ("train", train_imgs),
            ("val", val_imgs),
            ("test", test_imgs),
        ]:
            split_counts[split_name][cls] = len(split_imgs)
            for img_path in split_imgs:
                # Copy image
                dest_img = splits_dir / split_name / "images" / img_path.name
                shutil.copy2(img_path, dest_img)

                # Copy label
                src_label = labels_dir / cls / (img_path.stem + ".txt")
                dest_label = splits_dir / split_name / "labels" / (img_path.stem + ".txt")
                if src_label.exists():
                    shutil.copy2(src_label, dest_label)

    return split_counts


def generate_yolo_yaml(splits_dir: Path, output_path: Path) -> None:
    """Write a YOLO data.yaml file pointing to the split directories."""
    data = {
        "path": str(splits_dir.resolve()),
        "train": "train/images",
        "val": "val/images",
        "test": "test/images",
        "nc": len(CLASSES),
        "names": CLASSES,
    }
    with open(output_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def compute_dataset_stats(
    class_images: Dict[str, List[Path]],
    split_counts: Dict[str, Dict[str, int]],
) -> dict:
    """Compile and return dataset statistics as a JSON-serializable dict."""
    total = sum(len(v) for v in class_images.values())
    return {
        "total_images": total,
        "classes": CLASSES,
        "images_per_class": {cls: len(imgs) for cls, imgs in class_images.items()},
        "split_counts": split_counts,
        "split_ratios": {
            "train": TRAIN_SPLIT,
            "val": VAL_SPLIT,
            "test": TEST_SPLIT,
        },
        "min_images_per_class_required": MIN_IMAGES_PER_CLASS,
        "validation_passed": True,
    }


def prepare_dataset(
    raw_dir: str | Path = "data/raw",
    labels_dir: str | Path = "data/labels",
    splits_dir: str | Path = "data/splits",
    stats_output: str | Path = "data/dataset_stats.json",
) -> dict:
    """
    End-to-end dataset preparation pipeline.

    1. Validate dataset structure (raises if validation fails)
    2. Generate YOLO-format label files
    3. Create train/val/test splits
    4. Write YOLO data.yaml
    5. Output dataset statistics JSON

    Returns the stats dict.
    """
    raw_dir = Path(raw_dir)
    labels_dir = Path(labels_dir)
    splits_dir = Path(splits_dir)
    stats_output = Path(stats_output)

    print(f"[prepare_dataset] Validating dataset at: {raw_dir}")
    class_images = validate_dataset_structure(raw_dir)
    print(f"[prepare_dataset] Validation passed. Total images: "
          f"{sum(len(v) for v in class_images.values())}")

    print("[prepare_dataset] Generating YOLO label files...")
    create_label_files(class_images, labels_dir)

    print("[prepare_dataset] Creating train/val/test splits...")
    split_counts = create_splits(class_images, splits_dir, labels_dir)

    yolo_yaml_path = splits_dir / "data.yaml"
    generate_yolo_yaml(splits_dir, yolo_yaml_path)
    print(f"[prepare_dataset] YOLO data.yaml written to: {yolo_yaml_path}")

    stats = compute_dataset_stats(class_images, split_counts)
    stats_output.parent.mkdir(parents=True, exist_ok=True)
    with open(stats_output, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"[prepare_dataset] Stats written to: {stats_output}")

    for cls, count in stats["images_per_class"].items():
        print(f"  {cls}: {count} images total")
    for split, counts in split_counts.items():
        print(f"  {split}: {sum(counts.values())} images")

    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prepare RailOS defect detector dataset")
    parser.add_argument("--raw-dir", default="data/raw", help="Path to raw images directory")
    parser.add_argument("--labels-dir", default="data/labels", help="Path to labels output directory")
    parser.add_argument("--splits-dir", default="data/splits", help="Path to splits output directory")
    parser.add_argument("--stats-output", default="data/dataset_stats.json", help="Path for stats JSON")
    args = parser.parse_args()

    prepare_dataset(
        raw_dir=args.raw_dir,
        labels_dir=args.labels_dir,
        splits_dir=args.splits_dir,
        stats_output=args.stats_output,
    )
