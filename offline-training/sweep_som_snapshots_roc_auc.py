#!/usr/bin/env python3
"""
Sweep all SOM snapshots and produce ROC plots + AUC summary for CPU and Disk traces.

For each SOM snapshot:
- Run offline inference (UBL-NS, UBL-5PtS, k-NN) on:
  - artifacts/prometheus_samples_cpu_test.json
  - artifacts/prometheus_samples_disk_test.json
- Save per-snapshot ROC plot PNGs
- Compute AUC for each ROC curve (trapezoid over FPR->TPR)
- Write a single CSV summary with AUCs for both datasets

Requires:
  pip install matplotlib
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _roc_points(obj: Dict[str, Any], model_key: str) -> List[Dict[str, float]]:
    return list((((obj.get("evaluation") or {}).get("roc") or {}).get(model_key) or {}).get("points") or [])


def _auc_from_points(points: List[Dict[str, float]]) -> float:
    """
    Compute AUC with trapezoidal rule on ROC points.
    Ensures endpoints (0,0) and (1,1) exist.
    """
    xy: List[Tuple[float, float]] = []
    for p in points:
        if not isinstance(p, dict):
            continue
        if "fpr" not in p or "tpr" not in p:
            continue
        xy.append((float(p["fpr"]), float(p["tpr"])))

    if not xy:
        return float("nan")

    # Add endpoints and sort by FPR.
    xy.append((0.0, 0.0))
    xy.append((1.0, 1.0))
    xy = sorted(set(xy), key=lambda t: (t[0], t[1]))

    auc = 0.0
    for (x0, y0), (x1, y1) in zip(xy[:-1], xy[1:]):
        dx = max(0.0, float(x1 - x0))
        auc += dx * (float(y0) + float(y1)) / 2.0

    # Clamp for numeric noise.
    return float(max(0.0, min(1.0, auc)))


def _run_inference(
    run_script: Path,
    samples_json: Path,
    som_snapshot: Path,
    knn_snapshot: Path,
    out_json: Path,
    out_png: Path,
    title: str,
    pending_window_sec: float,
    anomaly_streak: int,
    roc_points: int,
) -> None:
    cmd = [
        sys.executable,
        str(run_script),
        "--samples-json",
        str(samples_json),
        "--som-snapshot",
        str(som_snapshot),
        "--knn-snapshot",
        str(knn_snapshot),
        "--pending-window-sec",
        str(float(pending_window_sec)),
        "--anomaly-streak",
        str(int(anomaly_streak)),
        "--roc-points",
        str(int(roc_points)),
        "--output-json",
        str(out_json),
        "--output-roc-png",
        str(out_png),
        "--plot-title",
        title,
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep SOM snapshots: ROC PNGs + AUC CSV (CPU+Disk)")
    ap.add_argument("--run-script", type=Path, default=Path("run_offline_inference.py"))
    ap.add_argument("--som-dir", type=Path, default=Path("../ubl-learner"))
    ap.add_argument("--knn-snapshot", type=Path, default=Path("../ubl-learner/knn_trained_snapshot.json"))
    ap.add_argument("--cpu-samples", type=Path, default=Path("artifacts/prometheus_samples_cpu_test.json"))
    ap.add_argument("--disk-samples", type=Path, default=Path("artifacts/prometheus_samples_disk_test.json"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/sweep_roc"))
    ap.add_argument("--pending-window-sec", type=float, default=10.0)
    ap.add_argument("--anomaly-streak", type=int, default=3)
    ap.add_argument("--roc-points", type=int, default=200)
    ap.add_argument("--csv", type=Path, default=Path("artifacts/sweep_roc/auc_summary.csv"))
    args = ap.parse_args()

    som_paths = sorted(args.som_dir.glob("som_trained_snapshot*.json"))
    if not som_paths:
        raise SystemExit(f"No SOM snapshots found in {args.som_dir}")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []

    for som in som_paths:
        som_name = som.name.replace(".json", "")

        # CPU
        cpu_out_json = args.out_dir / f"{som_name}__cpu_eval.json"
        cpu_out_png = args.out_dir / f"{som_name}__cpu_roc.png"
        _run_inference(
            args.run_script,
            args.cpu_samples,
            som,
            args.knn_snapshot,
            cpu_out_json,
            cpu_out_png,
            title=f"{som_name} | CPU ROC (W={args.pending_window_sec}s)",
            pending_window_sec=args.pending_window_sec,
            anomaly_streak=args.anomaly_streak,
            roc_points=args.roc_points,
        )
        cpu_obj = _load_json(cpu_out_json)

        # Disk
        disk_out_json = args.out_dir / f"{som_name}__disk_eval.json"
        disk_out_png = args.out_dir / f"{som_name}__disk_roc.png"
        _run_inference(
            args.run_script,
            args.disk_samples,
            som,
            args.knn_snapshot,
            disk_out_json,
            disk_out_png,
            title=f"{som_name} | Disk ROC (W={args.pending_window_sec}s)",
            pending_window_sec=args.pending_window_sec,
            anomaly_streak=args.anomaly_streak,
            roc_points=args.roc_points,
        )
        disk_obj = _load_json(disk_out_json)

        def aucs(obj: Dict[str, Any]) -> Tuple[float, float, float]:
            return (
                _auc_from_points(_roc_points(obj, "ubl_5pts")),
                _auc_from_points(_roc_points(obj, "ubl_ns")),
                _auc_from_points(_roc_points(obj, "knn")),
            )

        cpu_auc_5, cpu_auc_ns, cpu_auc_knn = aucs(cpu_obj)
        disk_auc_5, disk_auc_ns, disk_auc_knn = aucs(disk_obj)

        rows.append(
            {
                "som_snapshot": str(som),
                "som_name": som_name,
                "cpu_auc_ubl_5pts": cpu_auc_5,
                "cpu_auc_ubl_ns": cpu_auc_ns,
                "cpu_auc_knn": cpu_auc_knn,
                "disk_auc_ubl_5pts": disk_auc_5,
                "disk_auc_ubl_ns": disk_auc_ns,
                "disk_auc_knn": disk_auc_knn,
                "cpu_eval_json": str(cpu_out_json),
                "cpu_roc_png": str(cpu_out_png),
                "disk_eval_json": str(disk_out_json),
                "disk_roc_png": str(disk_out_png),
            }
        )

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "som_name",
                "som_snapshot",
                "cpu_auc_ubl_5pts",
                "cpu_auc_ubl_ns",
                "cpu_auc_knn",
                "disk_auc_ubl_5pts",
                "disk_auc_ubl_ns",
                "disk_auc_knn",
                "cpu_roc_png",
                "disk_roc_png",
                "cpu_eval_json",
                "disk_eval_json",
            ],
        )
        w.writeheader()
        for r in rows:
            # Format NaNs cleanly in CSV
            out = dict(r)
            for k, v in list(out.items()):
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    out[k] = ""
            w.writerow(out)

    print(f"[OK] Wrote {len(rows)} rows to {args.csv}")
    print(f"[OK] ROC PNGs + eval JSONs in {args.out_dir}")


if __name__ == "__main__":
    main()

