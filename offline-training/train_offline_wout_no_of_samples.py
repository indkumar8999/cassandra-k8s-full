#!/usr/bin/env python3
"""
Offline SOM Training Script

Imports SOM class and config from main.py.
Loads pre-collected metrics samples from JSON.
Trains a Self-Organizing Map (SOM) using collected samples.
Saves the trained model snapshot for later import/inference.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import main as learner_main

# Import implementation and config from main.py
from main import (
    Sample,
    LearnerState,
    SOM,
    THRESHOLD_PERCENTILE,
    TIER_A_AVG_FEATURES,
)


def _stop_imported_runtime() -> None:
    """Disable side-effect polling thread started by importing main.py."""
    imported_state = getattr(learner_main, "state", None)
    if imported_state is None:
        return
    if hasattr(imported_state, "running"):
        imported_state.running = False
    imported_thread = getattr(imported_state, "thread", None)
    if imported_thread is not None and imported_thread.is_alive():
        imported_thread.join(timeout=0.2)
    query_pool = getattr(imported_state, "query_pool", None)
    if query_pool is not None:
        query_pool.shutdown(wait=False, cancel_futures=True)


def _build_training_harness(offline_mode: bool = False) -> LearnerState:
    """Create a minimal LearnerState object without starting background threads."""
    state = object.__new__(LearnerState)
    state.phase = "offline"
    state.training_samples  = []
    state.norm_max = {}
    state.capacity_norm_max_cached = None
    state.capacity_norm_max_cached_at = None
    state.feature_order = []
    state.som = None
    state.area_map = None
    state.threshold = 0.0
    state.trained = False
    state.ready = False
    state.last_error = None
    state.training_duration_sec = 0.0
    state.training_start_ts = None
    state.training_end_ts = None
    state.offline_mode = offline_mode
    return state


def load_samples_from_json(samples_json_path: str) -> List[Dict[str, float]]:
    """Load collected sample dictionaries from a JSON file."""
    path = Path(samples_json_path)
    if not path.exists():
        raise FileNotFoundError(f"Samples JSON not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        samples = payload
    elif isinstance(payload, dict) and isinstance(payload.get("samples"), list):
        samples = payload["samples"]
    else:
        raise ValueError("Unsupported JSON format. Expected list or object with 'samples' list")

    normalized_samples: List[Dict[str, float]] = []
    dropped_records = 0
    for record in samples:
        if not isinstance(record, dict):
            dropped_records += 1
            continue
        if "values" in record and isinstance(record["values"], dict):
            values = record["values"]
        else:
            values = record
        cleaned_values = {key: float(value) for key, value in values.items() if isinstance(value, (int, float))}
        if not cleaned_values:
            dropped_records += 1
            continue
        normalized_samples.append(cleaned_values)

    print(f"[LOAD] Loaded {len(normalized_samples)} usable sample dictionaries from {path}")
    if dropped_records:
        print(f"[LOAD] Dropped {dropped_records} empty or invalid records")
    return normalized_samples


# === Data Normalization and Training ===
def normalize_and_train(
    samples: List[Dict[str, float]],
    state: LearnerState,
) -> tuple[SOM, np.ndarray, Dict[str, float], float]:
    """Convert raw samples and run main.py's LearnerState._train implementation."""
    if not samples:
        raise ValueError("No samples provided for training")

    print(f"[TRAIN] Processing {len(samples)} samples")
    state.training_samples = [
        Sample(
            ts=time.time(),
            values=sample,
            quality_valid=True,
            missing_required=[],
            missing_tier_b=[],
        )
        for sample in samples
    ]

    state._train()
    if state.som is None or state.area_map is None or not state.norm_max:
        raise RuntimeError(state.last_error or "Training failed in main.py LearnerState._train")

    if hasattr(state, "kfold_metrics"):
        print(f"[TRAIN] K-fold metrics from main.py: {state.kfold_metrics}")

    return state.som, state.area_map, dict(state.norm_max), float(state.threshold)


# === Snapshot Persistence ===
def save_snapshot(
    som: SOM,
    area_map: np.ndarray,
    norm_max: Dict[str, float],
    threshold: float,
    training_duration_sec: float,
    output_dir: str,
    output_file: str = "som_trained_snapshot.json",
) -> Path:
    """Save trained SOM snapshot to JSON file."""
    output_path = Path(output_dir) / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "som_rows": som.rows,
        "som_cols": som.cols,
        "feature_order": TIER_A_AVG_FEATURES,
        "norm_max": norm_max,
        "threshold": threshold,
        "threshold_percentile": float(THRESHOLD_PERCENTILE),
        "training_duration_sec": training_duration_sec,
        "weights": som.weights.tolist(),
        "area_map": area_map.tolist(),
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[SAVE] Snapshot saved to: {output_path}")
    print(f"[SAVE] Snapshot size: {output_path.stat().st_size / 1024:.1f} KB")
    return output_path


# === Main ===
def main():
    parser = argparse.ArgumentParser(
        description="Train SOM offline from pre-collected metrics samples JSON"
    )
    parser.add_argument(
        "--samples-json",
        default="./artifacts/prometheus_samples.json",
        help="Input JSON path containing collected samples (default: ./artifacts/prometheus_samples.json)",
    )
    parser.add_argument(
        "--output-dir",
        default="./artifacts",
        help="Output directory for snapshot (default: ./artifacts)",
    )
    parser.add_argument(
        "--output-file",
        default="som_trained_snapshot.json",
        help="Output filename (default: som_trained_snapshot.json)",
    )
    parser.add_argument(
        "--offline-mode",
        action="store_true",
        help="Skip Prometheus queries; use only observed sample maxima for normalization",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("Offline SOM Training from Samples JSON")
    print("=" * 80)
    print(f"Input samples JSON: {args.samples_json}")
    print("Training path: LearnerState._train from main.py")
    print("=" * 80)

    try:
        _stop_imported_runtime()
        state = _build_training_harness(offline_mode=args.offline_mode)

        # Load pre-collected metrics samples from JSON
        samples = load_samples_from_json(args.samples_json)

        if len(samples) == 0:
            print("[ERROR] No samples loaded; cannot train SOM")
            sys.exit(1)

        if args.offline_mode:
            print("[OFFLINE] Mode enabled: skipping Prometheus queries, using observed sample maxima")

        # Train SOM on all collected samples
        state.training_start_ts = time.time()
        som, area_map, norm_max, threshold = normalize_and_train(samples, state)
        state.training_end_ts = time.time()
        state.training_duration_sec = state.training_end_ts - state.training_start_ts

        print(f"[TRAIN] SOM training time: {state.training_duration_sec:.4f} sec")

        # Save snapshot
        output_path = save_snapshot(
            som,
            area_map,
            norm_max,
            threshold,
            state.training_duration_sec,
            args.output_dir,
            args.output_file,
        )

        print("=" * 80)
        print(f"✓ Training complete. Snapshot: {output_path}")
        print("=" * 80)
        print(f"Samples Collected: {len(samples)}")

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()