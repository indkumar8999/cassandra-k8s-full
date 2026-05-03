#!/usr/bin/env python3
"""Evaluate all SOM snapshots under ubl-learner/ against a labeled offline dataset.

Outputs
- Prints a sorted summary table (best AUC first)
- Writes:
  - artifacts/roc_sweep/<snapshot_stem>.roc.png
  - artifacts/roc_sweep/<snapshot_stem>.scores.csv
  - artifacts/roc_sweep/summary.json

This script uses the same scoring as `offline-training/eval_som_roc.py`.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

import numpy as np

from eval_som_roc import compute_scores, load_labeled_samples, load_snapshot


def safe_stem(path: Path) -> str:
    # Keep it filesystem friendly and stable.
    s = path.stem
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:140] or "snapshot"


def write_scores_csv(out_csv: Path, samples_path: Path, labels: np.ndarray, scores: np.ndarray) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(samples_path.read_text(encoding="utf-8"))
    rows = []
    for rec, label, score in zip(payload["samples"], labels.tolist(), scores.tolist()):
        ts = rec.get("ts") if isinstance(rec, dict) else None
        rows.append((ts, int(label), float(score)))

    import csv

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "label", "score"])  # label=1 means slo_violated
        w.writerows(rows)


def write_roc_png(out_png: Path, fpr: np.ndarray, tpr: np.ndarray, auc: float, title: str) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # type: ignore

    plt.figure(figsize=(6, 6))
    plt.plot(fpr, tpr, label=f"AUC = {auc:.4f}")
    plt.plot([0, 1], [0, 1], linestyle="--", color="gray", linewidth=1)
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title(title)
    plt.legend(loc="lower right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_png)
    plt.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate all ubl-learner SOM snapshots and rank by ROC AUC")
    parser.add_argument(
        "--samples-json",
        default="./offline-training/prometheus_samples_disk_test.json",
        help="Path to labeled samples JSON",
    )
    parser.add_argument(
        "--snapshots-dir",
        default="./ubl-learner",
        help="Directory containing snapshot JSONs",
    )
    parser.add_argument(
        "--out-dir",
        default="./artifacts/roc_sweep",
        help="Output directory for ROC PNGs / score CSVs / summary.json",
    )
    parser.add_argument(
        "--glob",
        default="som_trained_snapshot*.json",
        help="Glob for snapshot files inside snapshots-dir",
    )

    args = parser.parse_args()

    samples_path = Path(args.samples_json)
    snapshots_dir = Path(args.snapshots_dir)
    out_dir = Path(args.out_dir)

    sample_dicts, y_true = load_labeled_samples(samples_path)

    from sklearn.metrics import roc_auc_score, roc_curve  # type: ignore

    results: List[Dict] = []
    snapshot_paths = sorted(snapshots_dir.glob(args.glob))
    if not snapshot_paths:
        raise SystemExit(f"No snapshots found in {snapshots_dir} matching {args.glob!r}")

    for snap_path in snapshot_paths:
        try:
            snap = load_snapshot(snap_path)
            y_score = compute_scores(snap, sample_dicts)
            auc = float(roc_auc_score(y_true, y_score))
            fpr, tpr, _ = roc_curve(y_true, y_score)

            stem = safe_stem(snap_path)
            out_png = out_dir / f"{stem}.roc.png"
            out_csv = out_dir / f"{stem}.scores.csv"

            write_roc_png(out_png, fpr, tpr, auc, title=f"{snap_path.name} (AUC={auc:.4f})")
            write_scores_csv(out_csv, samples_path, y_true, y_score)

            results.append(
                {
                    "snapshot": str(snap_path),
                    "snapshot_name": snap_path.name,
                    "auc": auc,
                    "out_roc_png": str(out_png),
                    "out_scores_csv": str(out_csv),
                    "rows": snap.rows,
                    "cols": snap.cols,
                    "threshold": snap.threshold,
                    "feature_order": snap.feature_order,
                }
            )
        except Exception as ex:
            results.append({"snapshot": str(snap_path), "snapshot_name": snap_path.name, "error": str(ex)})

    # Sort with errors last
    def sort_key(r: Dict):
        if "auc" not in r:
            return (1, -1.0)
        return (0, -float(r["auc"]))

    results_sorted = sorted(results, key=sort_key)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(results_sorted, indent=2), encoding="utf-8")

    # Print a small table
    print(f"[OK] Evaluated {len(snapshot_paths)} snapshots")
    print("AUC     SNAPSHOT")
    print("------  ----------------------------------------------")
    for r in results_sorted:
        if "auc" in r:
            print(f"{r['auc']:.6f}  {r['snapshot_name']}")
        else:
            print(f"ERROR   {r['snapshot_name']}: {r.get('error')}")

    best = next((r for r in results_sorted if "auc" in r), None)
    if best:
        print("\n[BEST]")
        print(json.dumps(best, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
