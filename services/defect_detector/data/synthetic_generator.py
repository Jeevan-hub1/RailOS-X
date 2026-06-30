"""
RailOS Defect Detector — Synthetic Image Generator
Requirement: REQ-003 (Track Defect Detection)

Generates synthetic track defect images for testing using numpy + PIL.
Produces 100 images per class with plausible track textures and defect overlays.
Used as a pytest fixture via conftest.py::synthetic_dataset.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

CLASSES = ["crack", "flaking", "fastener_loose", "spalling"]
DEFAULT_IMAGES_PER_CLASS = 100
IMAGE_SIZE = (640, 640)
SEED = 42


def _rail_background(rng: np.random.Generator, size: tuple[int, int] = IMAGE_SIZE) -> np.ndarray:
    """
    Generate a plausible railway track texture background.
    Uses a grey concrete/ballast base with subtle noise and rail reflections.
    """
    h, w = size
    # Ballast base: mid-grey with gaussian noise
    base = rng.normal(loc=100, scale=15, size=(h, w)).clip(60, 200).astype(np.uint8)
    # Add horizontal rail bands (brighter steel)
    rail_top = int(h * 0.35)
    rail_bot = int(h * 0.65)
    base[rail_top:rail_bot, :] = np.clip(
        base[rail_top:rail_bot, :].astype(int) + 60, 0, 255
    ).astype(np.uint8)
    # Slight vertical vignette
    vignette = np.linspace(0.85, 1.0, w)
    base = (base * vignette).clip(0, 255).astype(np.uint8)
    # Convert to 3-channel RGB with slight color tint
    rgb = np.stack([
        (base * 0.78).clip(0, 255).astype(np.uint8),
        (base * 0.80).clip(0, 255).astype(np.uint8),
        (base * 0.85).clip(0, 255).astype(np.uint8),
    ], axis=-1)
    return rgb


def _add_crack(
    img_array: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Overlay a crack defect: dark jagged line across the rail surface."""
    img = Image.fromarray(img_array)
    draw = ImageDraw.Draw(img)
    h, w = img_array.shape[:2]
    # Start near mid-frame, jagged path
    x = int(rng.integers(w // 4, 3 * w // 4))
    y_start = int(rng.integers(h // 3, h // 2))
    points = [(x, y_start)]
    for _ in range(rng.integers(8, 16)):
        x += int(rng.integers(-12, 12))
        y_start += int(rng.integers(6, 20))
        points.append((x, max(0, min(h - 1, y_start))))
    draw.line(points, fill=(20, 20, 20), width=int(rng.integers(2, 5)))
    return np.array(img)


def _add_flaking(
    img_array: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Overlay flaking defect: irregular bright patches with roughened edges."""
    img = Image.fromarray(img_array)
    draw = ImageDraw.Draw(img)
    h, w = img_array.shape[:2]
    num_patches = int(rng.integers(3, 8))
    for _ in range(num_patches):
        cx = int(rng.integers(w // 4, 3 * w // 4))
        cy = int(rng.integers(h // 3, 2 * h // 3))
        rw = int(rng.integers(20, 60))
        rh = int(rng.integers(10, 35))
        color = (
            int(rng.integers(180, 230)),
            int(rng.integers(175, 220)),
            int(rng.integers(165, 210)),
        )
        draw.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=color)
    # Blur slightly to look natural
    result = np.array(img.filter(ImageFilter.GaussianBlur(radius=2)))
    return result


def _add_fastener_loose(
    img_array: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Overlay fastener_loose defect: missing or displaced fastener bolt shadow.
    Simulated as a dark oval with surrounding disrupted texture.
    """
    img = Image.fromarray(img_array)
    draw = ImageDraw.Draw(img)
    h, w = img_array.shape[:2]
    # Place 1–2 fastener anomalies
    for _ in range(int(rng.integers(1, 3))):
        cx = int(rng.integers(w // 5, 4 * w // 5))
        cy = int(rng.integers(h // 3, 2 * h // 3))
        r = int(rng.integers(12, 22))
        # Shadow (dark) indicates absent fastener
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(25, 25, 25))
        # Light ring around shadow = disturbed rail material
        draw.ellipse(
            [cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5],
            outline=(210, 200, 190),
            width=3,
        )
    return np.array(img)


def _add_spalling(
    img_array: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Overlay spalling defect: irregular craters / pitting on rail head surface.
    Simulated as dark irregular polygons with bright rims.
    """
    img = Image.fromarray(img_array)
    draw = ImageDraw.Draw(img)
    h, w = img_array.shape[:2]
    num_pits = int(rng.integers(4, 10))
    for _ in range(num_pits):
        cx = int(rng.integers(w // 4, 3 * w // 4))
        cy = int(rng.integers(h // 3, 2 * h // 3))
        # Irregular polygon
        n_pts = int(rng.integers(5, 9))
        angles = sorted(rng.uniform(0, 2 * np.pi, n_pts))
        radii = rng.uniform(8, 25, n_pts)
        pts = [
            (
                int(cx + r * np.cos(a)),
                int(cy + r * np.sin(a)),
            )
            for r, a in zip(radii, angles)
        ]
        draw.polygon(pts, fill=(40, 38, 36))
        draw.polygon(pts, outline=(200, 195, 185))
    return np.array(img)


_DEFECT_GENERATORS = {
    "crack": _add_crack,
    "flaking": _add_flaking,
    "fastener_loose": _add_fastener_loose,
    "spalling": _add_spalling,
}


def generate_synthetic_image(
    cls: str,
    rng: np.random.Generator,
    size: tuple[int, int] = IMAGE_SIZE,
) -> Image.Image:
    """
    Generate a single synthetic track defect image for the given class.

    Args:
        cls: Defect class name (must be in CLASSES).
        rng: Numpy random generator for reproducibility.
        size: Output image size (H, W).

    Returns:
        PIL Image (RGB, 640×640 by default).
    """
    if cls not in _DEFECT_GENERATORS:
        raise ValueError(f"Unknown class '{cls}'. Valid classes: {CLASSES}")
    background = _rail_background(rng, size=size)
    defect_fn = _DEFECT_GENERATORS[cls]
    defect_array = defect_fn(background, rng)
    return Image.fromarray(defect_array.astype(np.uint8))


def generate_synthetic_dataset(
    output_dir: str | Path,
    images_per_class: int = DEFAULT_IMAGES_PER_CLASS,
    seed: int = SEED,
    size: tuple[int, int] = IMAGE_SIZE,
) -> Path:
    """
    Generate a full synthetic dataset with `images_per_class` images per defect class.
    Saves images as PNG files under output_dir/<class>/<class>_NNNN.png.

    Args:
        output_dir: Root directory for the synthetic dataset.
        images_per_class: Number of images to generate per class.
        seed: Random seed for reproducibility.
        size: Image dimensions (H, W).

    Returns:
        Path to the output_dir.
    """
    output_dir = Path(output_dir)
    rng = np.random.default_rng(seed)

    for cls in CLASSES:
        cls_dir = output_dir / cls
        cls_dir.mkdir(parents=True, exist_ok=True)
        for i in range(images_per_class):
            img = generate_synthetic_image(cls, rng, size=size)
            img_path = cls_dir / f"{cls}_{i:04d}.png"
            img.save(img_path)
        print(f"[synthetic_generator] Generated {images_per_class} images for class '{cls}' → {cls_dir}")

    print(f"[synthetic_generator] Done. Total: {len(CLASSES) * images_per_class} images in {output_dir}")
    return output_dir


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic RailOS defect images")
    parser.add_argument("--output-dir", default="data/synthetic", help="Output directory")
    parser.add_argument("--images-per-class", type=int, default=DEFAULT_IMAGES_PER_CLASS)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    generate_synthetic_dataset(
        output_dir=args.output_dir,
        images_per_class=args.images_per_class,
        seed=args.seed,
    )
