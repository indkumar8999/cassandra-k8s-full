#!/usr/bin/env python3
"""
Offline kNN Training Script

Builds a pretrained kNN snapshot (reference vectors + tau threshold) from the same
Prometheus samples JSON used by offline SOM training.

Outputs a JSON snapshot that the online learner can load via KNN_SNAPSHOT_PATH.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

import main as learner_main

# Reuse the offline-training main.py implementation for feature extraction + config.
from main import (
    Sample,
    LearnerState,
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


def _build_training_harness() -> LearnerState:
    """Create a minimal LearnerState object without starting background threads."""
    state = object.__new__(LearnerState)
    state.phase = "offline_knn"
    state.training_samples = []
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
    state.offline_mode = True
    return state


def load_samples_from_json(samples_json_path: str) -> List[Dict[str, float]]:
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

    normalized: List[Dict[str, float]] = []
    for record in samples:
        if not isinstance(record, dict):
            continue
        values = record.get("values") if isinstance(record.get("values"), dict) else record
        cleaned = {str(k): float(v) for k, v in values.items() if isinstance(v, (int, float))}
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _vectorize_raw(state: LearnerState, values: Dict[str, float]) -> np.ndarray:
    """
    Use the same averaging logic as the learner: avg tier-A metrics across pods.
    """
    sample = Sample(ts=time.time(), values=values, quality_valid=True, missing_required=[], missing_tier_b=[])
    avg = state._avg_tier_a_features(sample)
    return np.array([avg[f] for f in TIER_A_AVG_FEATURES], dtype=np.float64)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train kNN offline from Prometheus samples JSON")
    parser.add_argument("--samples-json", default="./artifacts/prometheus_samples.json")
    parser.add_argument("--output-dir", default="./artifacts")
    parser.add_argument("--output-file", default="knn_trained_snapshot.json")
    parser.add_argument("--k", type=int, default=5)
    # Keep flag for compatibility, but default behavior is to train on ALL samples.
    # If provided (>0), it caps the number of reference vectors.
    parser.add_argument("--ref-size", type=int, default=0)
    parser.add_argument("--tau-percentile", type=float, default=95.0)
    args = parser.parse_args()

    train_started = time.time()
    _stop_imported_runtime()
    state = _build_training_harness()

    samples = load_samples_from_json(args.samples_json)
    if not samples:
        print("[ERROR] No samples loaded", file=sys.stderr)
        sys.exit(1)

    X_raw = np.vstack([_vectorize_raw(state, s) for s in samples])
    # observed maxima normalization (offline_mode=True skips capacity queries in this main.py)
    state.feature_order = list(TIER_A_AVG_FEATURES)
    state.norm_max = {name: float(max(X_raw[:, i].max(), 1e-9)) for i, name in enumerate(state.feature_order)}
    denom = np.array([state.norm_max[f] for f in state.feature_order], dtype=np.float64)
    X_norm = (X_raw / denom) * 100.0

    # Train on ALL samples by default.
    total_n = int(X_norm.shape[0])
    cap = int(args.ref_size)
    ref_n = total_n if cap <= 0 else max(1, min(cap, total_n))
    X_ref = np.asarray(X_norm[:ref_n], dtype=np.float64)

    # Baseline leave-one-out-ish scores: use (k+1)th neighbor to skip self-distance.
    k = max(1, int(args.k))
    k_excl = min(k + 1, ref_n)
    baseline_scores = np.zeros((ref_n,), dtype=np.float64)
    for i in range(ref_n):
        d = np.linalg.norm(X_ref - X_ref[i], axis=1)
        baseline_scores[i] = float(np.partition(d, k_excl - 1)[k_excl - 1])

    tau_pct = float(min(max(float(args.tau_percentile), 0.0), 100.0))
    tau = float(np.percentile(baseline_scores, tau_pct))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / args.output_file
    training_duration_sec = float(time.time() - train_started)
    payload = {
        "feature_order": list(TIER_A_AVG_FEATURES),
        "norm_max": dict(state.norm_max),
        "k": k,
        "ref_size": int(ref_n),
        "tau_percentile": tau_pct,
        "tau": tau,
        "ref_vectors": X_ref.tolist(),
        "created_at_unix": time.time(),
        "source_samples": str(args.samples_json),
        "training_duration_sec": training_duration_sec,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"[SAVE] kNN snapshot saved to {out_path} "
        f"(ref={ref_n}/{total_n}, k={k}, tau={tau:.6f} @P{tau_pct}, train_sec={training_duration_sec:.3f})"
    )


if __name__ == "__main__":
    main()

