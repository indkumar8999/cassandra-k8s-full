#!/usr/bin/env python3
"""Evaluate a pretrained UBL SOM snapshot against an offline labeled dataset.

Contract
- Inputs:
  - --snapshot-json: path to SOM snapshot exported by offline training.
  - --samples-json: metrics samples JSON (expects samples[].values and samples[].slo.slo_violated).
- Output:
  - Prints ROC AUC and saves ROC curve PNG.
  - Optionally writes per-sample scores CSV.

Scoring model
- Reuses the same scoring semantics as `ubl-learner/main.py`:
  1) Build the average tier-a feature vector across cassandra pods for each base feature.
  2) Normalize with snapshot norm_max: (raw/denom)*100.
  3) Find BMU on SOM weights.
  4) Score = area_map[BMU]. (Higher => more anomalous)
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np


@dataclass(frozen=True)
class Snapshot:
    rows: int
    cols: int
    feature_order: List[str]
    norm_max: Dict[str, float]
    threshold: float
    weights: np.ndarray  # (rows, cols, dims)
    area_map: np.ndarray  # (rows, cols)


def load_snapshot(path: Path) -> Snapshot:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    required_keys = ("som_rows", "som_cols", "feature_order", "norm_max", "threshold", "weights", "area_map")
    for k in required_keys:
        if k not in data:
            raise ValueError(f"Snapshot missing required key: {k}")

    feature_order = [str(x) for x in data["feature_order"]]
    rows = int(data["som_rows"])
    cols = int(data["som_cols"])
    dims = len(feature_order)

    weights = np.asarray(data["weights"], dtype=np.float64)
    if weights.shape != (rows, cols, dims):
        raise ValueError(f"Snapshot weights shape {weights.shape} != {(rows, cols, dims)}")

    area_map = np.asarray(data["area_map"], dtype=np.float64)
    if area_map.shape != (rows, cols):
        raise ValueError(f"Snapshot area_map shape {area_map.shape} != {(rows, cols)}")

    raw_norm = data["norm_max"]
    if not isinstance(raw_norm, dict):
        raise ValueError("Snapshot norm_max must be an object")
    norm_max = {str(k): float(v) for k, v in raw_norm.items()}
    for name in feature_order:
        if name not in norm_max:
            raise ValueError(f"Snapshot norm_max missing key: {name}")

    return Snapshot(
        rows=rows,
        cols=cols,
        feature_order=feature_order,
        norm_max=norm_max,
        threshold=float(data["threshold"]),
        weights=weights,
        area_map=area_map,
    )


def som_bmu(weights: np.ndarray, vec: np.ndarray) -> Tuple[int, int]:
    dists = np.linalg.norm(weights - vec, axis=2)
    return tuple(np.unravel_index(np.argmin(dists), dists.shape))  # type: ignore[return-value]


def avg_tier_a_features(values: Dict[str, float], feature_order: List[str]) -> Dict[str, float]:
    # Snapshot stores base metric names; dataset stores per-pod metric keys with __cassandra-X suffix.
    out: Dict[str, float] = {}
    for base in feature_order:
        per_pod = [v for k, v in values.items() if k.startswith(f"{base}__")]
        out[base] = float(np.mean(per_pod)) if per_pod else 0.0
    return out


def normalize_vector(avg_features: Dict[str, float], feature_order: List[str], norm_max: Dict[str, float]) -> np.ndarray:
    raw = np.array([float(avg_features.get(name, 0.0)) for name in feature_order], dtype=np.float64)
    denom = np.array([max(float(norm_max[name]), 1e-9) for name in feature_order], dtype=np.float64)
    return (raw / denom) * 100.0


def load_labeled_samples(samples_path: Path) -> Tuple[List[Dict[str, float]], np.ndarray]:
    with samples_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise ValueError("Expected top-level object with 'samples' list")

    samples: List[Dict[str, float]] = []
    labels: List[int] = []

    for rec in payload["samples"]:
        if not isinstance(rec, dict):
            continue
        values = rec.get("values")
        slo = rec.get("slo")
        if not isinstance(values, dict) or not isinstance(slo, dict):
            continue
        violated = bool(slo.get("slo_violated", False))

        cleaned = {str(k): float(v) for k, v in values.items() if isinstance(v, (int, float))}
        if not cleaned:
            continue
        samples.append(cleaned)
        labels.append(1 if violated else 0)

    if not samples:
        raise ValueError("No usable labeled samples found")

    return samples, np.asarray(labels, dtype=np.int32)


def compute_scores(snapshot: Snapshot, samples: List[Dict[str, float]]) -> np.ndarray:
    scores: List[float] = []
    for values in samples:
        avg = avg_tier_a_features(values, snapshot.feature_order)
        vec = normalize_vector(avg, snapshot.feature_order, snapshot.norm_max)
        r, c = som_bmu(snapshot.weights, vec)
        scores.append(float(snapshot.area_map[r, c]))
    return np.asarray(scores, dtype=np.float64)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SOM snapshot inference and plot ROC AUC")
    parser.add_argument(
        "--snapshot-json",
        default="./artifacts/som-snapshot.json",
        help="Path to SOM snapshot JSON (default: ./artifacts/som-snapshot.json)",
    )
    parser.add_argument(
        "--samples-json",
        default="./offline-training/prometheus_samples_disk_test.json",
        help="Path to labeled samples JSON (default: ./offline-training/prometheus_samples_disk_test.json)",
    )
    parser.add_argument(
        "--out-roc-png",
        default="./artifacts/roc_curve.png",
        help="Output ROC curve PNG path (default: ./artifacts/roc_curve.png)",
    )
    parser.add_argument(
        "--out-scores-csv",
        default="",
        help="Optional output CSV with columns: ts,label,score",
    )

    args = parser.parse_args()

    snapshot_path = Path(args.snapshot_json)
    samples_path = Path(args.samples_json)
    out_png = Path(args.out_roc_png)

    snap = load_snapshot(snapshot_path)
    samples, y_true = load_labeled_samples(samples_path)
    y_score = compute_scores(snap, samples)

    # Dependencies are intentionally local to this block, so the script still "imports" without them.
    from sklearn.metrics import roc_auc_score, roc_curve  # type: ignore

    auc = float(roc_auc_score(y_true, y_score))
    fpr, tpr, _ = roc_curve(y_true, y_score)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # type: ignore

    plt.figure(figsize=(6, 6))
    plt.plot(fpr, tpr, label=f"AUC = {auc:.4f}")
    plt.plot([0, 1], [0, 1], linestyle="--", color="gray", linewidth=1)
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("UBL SOM ROC Curve")
    plt.legend(loc="lower right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_png)

    if args.out_scores_csv:
        out_csv = Path(args.out_scores_csv)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with samples_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        rows = []
        for rec, label, score in zip(payload["samples"], y_true.tolist(), y_score.tolist()):
            ts = rec.get("ts") if isinstance(rec, dict) else None
            rows.append((ts, int(label), float(score)))
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "label", "score"])  # label=1 means slo_violated
            w.writerows(rows)

    print(f"[OK] Samples: {len(samples)}  Positives: {int(y_true.sum())}  Negatives: {int((1 - y_true).sum())}")
    print(f"[OK] ROC AUC: {auc:.6f}")
    print(f"[OK] ROC curve written: {out_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
