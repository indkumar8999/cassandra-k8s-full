#!/usr/bin/env python3
"""
Offline SOM Training Script

Imports SOM class and config from main.py.
Fetches metrics directly from Prometheus.
Trains a Self-Organizing Map (SOM) using collected samples.
Saves the trained model snapshot for later import/inference.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np
import main as learner_main

# Import implementation and config from main.py
from main import (
    Sample,
    LearnerState,
    SOM,
    PROMETHEUS_BASE as DEFAULT_PROMETHEUS_BASE,
    THRESHOLD_PERCENTILE,
    CASSANDRA_PODS,
    TARGET_NAMESPACE,
    TIER_A_NODE_QUERY_TEMPLATES,
    TIER_A_AVG_FEATURES,
)


def _build_training_harness() -> LearnerState:
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
    return state


# === Metrics Collection ===
def fetch_metrics_samples(
    duration_sec: int,
    poll_interval: float,
    state: LearnerState,
) -> List[Dict[str, float]]:
    """
    Poll Prometheus every poll_interval seconds for duration_sec.
    Collect raw metric samples for each pod and metric.

    Returns:
        List of dicts with keys like "metric__pod" and values as floats.
    """
    samples: List[Dict[str, float]] = []
    start_time = time.time()
    end_time = start_time + duration_sec

    print(f"[COLLECT] Starting metrics collection for {duration_sec}s (interval: {poll_interval}s)")
    print(f"[COLLECT] Prometheus: {learner_main.PROMETHEUS_BASE}")
    print(f"[COLLECT] Pods: {CASSANDRA_PODS}")

    while time.time() < end_time:
        sample_dict: Dict[str, float] = {}

        # Query each pod + metric combination
        for pod in CASSANDRA_PODS:
            for base_name, template in TIER_A_NODE_QUERY_TEMPLATES.items():
                query = template.replace("__NAMESPACE__", TARGET_NAMESPACE).replace("__POD__", pod)
                value = state._query_prom(query)
                key = f"{base_name}__{pod}"

                if value is not None:
                    sample_dict[key] = value
                else:
                    print(f"[COLLECT] Missing metric: {key}")

        if sample_dict:
            samples.append(sample_dict)
            print(f"[COLLECT] Sample {len(samples)}: {len(sample_dict)} metrics collected")

        elapsed = time.time() - start_time
        remaining = end_time - time.time()
        if remaining > 0:
            sleep_time = min(poll_interval, remaining)
            print(f"[COLLECT] Progress: {elapsed:.1f}s / {duration_sec}s, sleeping {sleep_time:.1f}s...")
            time.sleep(sleep_time)

    print(f"[COLLECT] Collection complete: {len(samples)} samples")
    return samples


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
        description="Train SOM offline from Prometheus metrics"
    )
    parser.add_argument(
        "--prometheus-base",
        default=DEFAULT_PROMETHEUS_BASE,
        help=f"Prometheus base URL (default: {DEFAULT_PROMETHEUS_BASE})",
    )
    parser.add_argument(
        "--duration-sec",
        type=int,
        default=180,
        help="Metrics collection duration in seconds (default: 180)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0)",
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

    args = parser.parse_args()

    print("=" * 80)
    print("Offline SOM Training from Prometheus")
    print("=" * 80)
    print(f"Prometheus: {args.prometheus_base}")
    print(f"Duration: {args.duration_sec}s, Poll interval: {args.poll_interval}s")
    print("Training path: LearnerState._train from main.py")
    print("=" * 80)

    try:
        learner_main.PROMETHEUS_BASE = args.prometheus_base
        state = _build_training_harness()

        # Collect metrics from Prometheus for the full requested duration
        samples = fetch_metrics_samples(
            args.duration_sec,
            args.poll_interval,
            state,
        )

        if len(samples) == 0:
            print("[ERROR] No samples collected; cannot train SOM")
            sys.exit(1)

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