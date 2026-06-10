"""
RailOS Defect Detector — TensorRT INT8 Export Script
Requirement: REQ-003 (Track Defect Detection)

Exports a trained YOLOv8n .pt checkpoint to a TensorRT INT8 engine targeting
Jetson Orin NX. Runs a latency benchmark (50 warm-up + 100 timed inferences)
and asserts p95 latency ≤ 100ms. Falls back to FP16 if INT8 calibration data
is unavailable.

Usage (on Jetson Orin NX with TensorRT installed):
    python export_tensorrt.py --weights runs/train/defect_detector/weights/best.pt
    python export_tensorrt.py --weights best.pt --fp16-fallback --no-benchmark
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False

LATENCY_BUDGET_MS = 100.0  # p95 latency must be ≤ 100ms (REQ-003)
WARMUP_RUNS = 50
BENCHMARK_RUNS = 100
INPUT_SIZE = (1, 3, 640, 640)  # batch=1, RGB, 640×640


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export YOLOv8n to TensorRT INT8 engine for Jetson Orin NX"
    )
    parser.add_argument(
        "--weights",
        required=True,
        help="Path to trained YOLOv8n .pt checkpoint",
    )
    parser.add_argument(
        "--device",
        default="0",
        help="CUDA device index (default: 0)",
    )
    parser.add_argument(
        "--calib-data",
        default=None,
        help="Path to calibration images directory for INT8 calibration. "
             "If not provided, falls back to FP16.",
    )
    parser.add_argument(
        "--fp16-fallback",
        action="store_true",
        help="Force FP16 export regardless of calibration data availability",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="Skip latency benchmark after export",
    )
    parser.add_argument(
        "--benchmark-output",
        default="export/benchmark_results.json",
        help="Path to write benchmark results JSON",
    )
    parser.add_argument(
        "--output-dir",
        default="export",
        help="Directory for exported engine and artifacts",
    )
    return parser.parse_args()


def _determine_quantization(calib_data: Optional[str], fp16_fallback: bool) -> tuple[bool, bool, str]:
    """
    Decide whether to export INT8 or fall back to FP16.

    Returns:
        (use_int8, use_fp16, reason_string)
    """
    if fp16_fallback:
        return False, True, "fp16-fallback flag set"
    if calib_data is None or not Path(calib_data).exists():
        return False, True, "INT8 calibration data not available — falling back to FP16"
    # Count calibration images
    calib_dir = Path(calib_data)
    calib_images = list(calib_dir.glob("**/*.png")) + list(calib_dir.glob("**/*.jpg"))
    if len(calib_images) < 10:
        return False, True, f"Insufficient calibration images ({len(calib_images)}) — falling back to FP16"
    return True, False, f"INT8 calibration with {len(calib_images)} images from {calib_data}"


def export_model(
    weights_path: Path,
    device: str,
    use_int8: bool,
    use_fp16: bool,
    calib_data: Optional[str],
    output_dir: Path,
) -> Path:
    """
    Export YOLOv8n checkpoint to TensorRT engine.

    Args:
        weights_path: Path to .pt checkpoint.
        device: CUDA device string.
        use_int8: Export with INT8 quantization.
        use_fp16: Export with FP16 quantization.
        calib_data: Path to INT8 calibration directory (None if FP16).
        output_dir: Directory to place the exported engine.

    Returns:
        Path to the exported .engine file.

    Raises:
        RuntimeError: If ultralytics is not available or export fails.
        FileNotFoundError: If weights_path does not exist.
    """
    if not ULTRALYTICS_AVAILABLE:
        raise RuntimeError(
            "ultralytics package required. Install: pip install ultralytics==8.2.0"
        )
    if not weights_path.exists():
        raise FileNotFoundError(f"Weights not found: {weights_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[export] Loading model from: {weights_path}")
    model = YOLO(str(weights_path))

    export_kwargs = {
        "format": "engine",
        "device": device,
        "imgsz": 640,
        "half": use_fp16 and not use_int8,
        "int8": use_int8,
        "simplify": True,
        "verbose": False,
    }
    if use_int8 and calib_data:
        export_kwargs["data"] = calib_data

    quant_label = "INT8" if use_int8 else "FP16"
    print(f"[export] Exporting to TensorRT {quant_label} engine...")
    engine_path = model.export(**export_kwargs)
    print(f"[export] Engine exported to: {engine_path}")
    return Path(engine_path)


def run_latency_benchmark(
    engine_path: Path,
    device: str,
    warmup_runs: int = WARMUP_RUNS,
    timed_runs: int = BENCHMARK_RUNS,
) -> dict:
    """
    Run a latency benchmark on the exported TensorRT engine.

    Performs `warmup_runs` inferences (discarded), then `timed_runs` timed
    inferences and computes latency statistics.

    Args:
        engine_path: Path to the .engine file.
        device: CUDA device string.
        warmup_runs: Number of warm-up inferences.
        timed_runs: Number of timed inferences.

    Returns:
        dict with latency statistics in milliseconds and a `pass` boolean.

    Raises:
        AssertionError: If p95 latency > LATENCY_BUDGET_MS.
    """
    if not ULTRALYTICS_AVAILABLE:
        raise RuntimeError("ultralytics required for benchmark")
    if not engine_path.exists():
        raise FileNotFoundError(f"Engine not found: {engine_path}")

    print(f"[benchmark] Loading TensorRT engine: {engine_path}")
    model = YOLO(str(engine_path))

    # Create a random input image (uint8 numpy array)
    dummy_input = np.random.randint(0, 256, (640, 640, 3), dtype=np.uint8)

    print(f"[benchmark] Warming up: {warmup_runs} runs...")
    for _ in range(warmup_runs):
        _ = model.predict(source=dummy_input, verbose=False, device=device)

    print(f"[benchmark] Timing: {timed_runs} runs...")
    latencies_ms: list[float] = []
    for _ in range(timed_runs):
        t0 = time.perf_counter()
        _ = model.predict(source=dummy_input, verbose=False, device=device)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    latencies = np.array(latencies_ms)
    stats = {
        "warmup_runs": warmup_runs,
        "timed_runs": timed_runs,
        "latency_mean_ms": float(np.mean(latencies)),
        "latency_median_ms": float(np.median(latencies)),
        "latency_p95_ms": float(np.percentile(latencies, 95)),
        "latency_p99_ms": float(np.percentile(latencies, 99)),
        "latency_min_ms": float(np.min(latencies)),
        "latency_max_ms": float(np.max(latencies)),
        "latency_budget_ms": LATENCY_BUDGET_MS,
        "pass": float(np.percentile(latencies, 95)) <= LATENCY_BUDGET_MS,
    }

    p95 = stats["latency_p95_ms"]
    status = "PASS" if stats["pass"] else "FAIL"
    print(
        f"[benchmark] {status}: p95 latency = {p95:.2f}ms "
        f"(budget: {LATENCY_BUDGET_MS}ms)"
    )

    if not stats["pass"]:
        raise AssertionError(
            f"p95 latency {p95:.2f}ms exceeds 100ms budget (REQ-003). "
            "Consider optimizing the model or increasing batch size."
        )

    return stats


def main() -> None:
    args = parse_args()
    weights_path = Path(args.weights)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    use_int8, use_fp16, reason = _determine_quantization(args.calib_data, args.fp16_fallback)
    quant_label = "INT8" if use_int8 else "FP16"
    print(f"[export] Quantization: {quant_label} — {reason}")

    engine_path = export_model(
        weights_path=weights_path,
        device=args.device,
        use_int8=use_int8,
        use_fp16=use_fp16,
        calib_data=args.calib_data,
        output_dir=output_dir,
    )

    result = {
        "weights_path": str(weights_path),
        "engine_path": str(engine_path),
        "quantization": quant_label,
        "quantization_reason": reason,
        "device": args.device,
    }

    if not args.no_benchmark:
        benchmark_stats = run_latency_benchmark(
            engine_path=engine_path,
            device=args.device,
        )
        result["benchmark"] = benchmark_stats

    # Write summary JSON
    benchmark_output = Path(args.benchmark_output)
    benchmark_output.parent.mkdir(parents=True, exist_ok=True)
    with open(benchmark_output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[export] Results written to: {benchmark_output}")


if __name__ == "__main__":
    main()
