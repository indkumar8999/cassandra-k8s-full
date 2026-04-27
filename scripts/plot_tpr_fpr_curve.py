#!/usr/bin/env python3
"""Generate a TPR vs FPR curve from score_stream.json.

Labeling rule (ground truth positive):
- A row at timestamp t is positive if there exists a breach timestamp b
  (slo_violated == True) such that t is in [b - window_seconds, b).

Prediction score:
- Uses a continuous score field (default: score_area).
- Sweeps thresholds to build ROC points (FPR, TPR).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import matplotlib.pyplot as plt


def load_items(input_path: Path) -> List[dict]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if not isinstance(items, list):
        raise ValueError("Expected 'items' to be a list in input JSON")
    return items


def build_labels_and_scores(
    items: Sequence[dict], window_seconds: float, score_key: str
) -> Tuple[List[float], List[int], List[float]]:
    ts: List[float] = []
    y_score: List[float] = []
    breach_ts: List[float] = []

    for item in items:
        t = item.get("ts")
        if t is None:
            continue
        t_float = float(t)
        ts.append(t_float)
        y_score.append(float(item.get(score_key, 0.0)))
        if item.get("slo_violated") is True:
            breach_ts.append(t_float)

    breach_ts.sort()

    y_true: List[int] = []
    for t in ts:
        is_positive = any((b > t) and (b <= t + window_seconds) for b in breach_ts)
        y_true.append(1 if is_positive else 0)

    return ts, y_true, y_score


def safe_div(n: int, d: int) -> float:
    return float(n) / float(d) if d > 0 else 0.0


def compute_roc_points(y_true: Sequence[int], y_score: Sequence[float]) -> List[Dict[str, float]]:
    unique_scores = sorted(set(y_score), reverse=True)
    thresholds = [float("inf")] + unique_scores + [float("-inf")]

    points: List[Dict[str, float]] = []

    for th in thresholds:
        pred = [1 if s >= th else 0 for s in y_score]
        tp = sum(1 for p, y in zip(pred, y_true) if p == 1 and y == 1)
        fp = sum(1 for p, y in zip(pred, y_true) if p == 1 and y == 0)
        fn = sum(1 for p, y in zip(pred, y_true) if p == 0 and y == 1)
        tn = sum(1 for p, y in zip(pred, y_true) if p == 0 and y == 0)

        tpr = safe_div(tp, tp + fn)
        fpr = safe_div(fp, fp + tn)

        points.append(
            {
                "threshold": th,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
                "tpr": tpr,
                "fpr": fpr,
            }
        )

    return points


def compute_auc(points: Sequence[Dict[str, float]]) -> float:
    # For ROC AUC we integrate TPR over FPR after sorting by FPR.
    sorted_points = sorted(points, key=lambda p: (p["fpr"], p["tpr"]))
    area = 0.0
    for i in range(1, len(sorted_points)):
        x0 = sorted_points[i - 1]["fpr"]
        y0 = sorted_points[i - 1]["tpr"]
        x1 = sorted_points[i]["fpr"]
        y1 = sorted_points[i]["tpr"]
        area += (x1 - x0) * (y0 + y1) * 0.5
    return area


def write_points_csv(path: Path, points: Sequence[Dict[str, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["threshold", "fpr", "tpr", "tp", "fp", "fn", "tn"])
        for p in points:
            writer.writerow(
                [
                    p["threshold"],
                    p["fpr"],
                    p["tpr"],
                    p["tp"],
                    p["fp"],
                    p["fn"],
                    p["tn"],
                ]
            )


def plot_curve(path: Path, points: Sequence[Dict[str, float]], title: str) -> None:
    fpr = [p["fpr"] for p in points]
    tpr = [p["tpr"] for p in points]

    plt.figure(figsize=(7, 6))
    plt.plot(fpr, tpr, marker=".", linewidth=1.2)
    plt.plot([0, 1], [0, 1], linestyle="--", linewidth=1)
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title(title)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build TPR vs FPR curve from score_stream.json")
    parser.add_argument("input", type=Path, help="Path to score_stream.json")
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=10.0,
        help="Pre-breach labeling window in seconds (default: 10)",
    )
    parser.add_argument(
        "--score-key",
        default="score_area",
        help="Continuous score key used for threshold sweep (default: score_area)",
    )
    parser.add_argument(
        "--output-png",
        type=Path,
        default=None,
        help="Output PNG path (default: <input_stem>_tpr_fpr_curve.png)",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="Output CSV path for ROC points (default: <input_stem>_tpr_fpr_points.csv)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Output JSON summary path (default: <input_stem>_tpr_fpr_summary.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path: Path = args.input
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_png = (
        args.output_png
        if args.output_png is not None
        else input_path.with_name(f"{input_path.stem}_tpr_fpr_curve.png")
    )
    output_csv = (
        args.output_csv
        if args.output_csv is not None
        else input_path.with_name(f"{input_path.stem}_tpr_fpr_points.csv")
    )
    output_json = (
        args.output_json
        if args.output_json is not None
        else input_path.with_name(f"{input_path.stem}_tpr_fpr_summary.json")
    )

    items = load_items(input_path)
    ts, y_true, y_score = build_labels_and_scores(
        items=items,
        window_seconds=args.window_seconds,
        score_key=args.score_key,
    )
    points = compute_roc_points(y_true=y_true, y_score=y_score)
    auc = compute_auc(points)

    title = f"TPR vs FPR ({args.score_key}, window={args.window_seconds}s)"
    plot_curve(output_png, points, title)
    write_points_csv(output_csv, points)

    summary = {
        "input_file": str(input_path),
        "window_seconds": args.window_seconds,
        "score_key": args.score_key,
        "n_rows_used": len(ts),
        "n_positive_labels": sum(y_true),
        "n_negative_labels": len(y_true) - sum(y_true),
        "auc": auc,
        "outputs": {
            "png": str(output_png),
            "csv": str(output_csv),
        },
    }
    output_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Input: {input_path}")
    print(f"Rows used: {len(ts)}")
    print(f"Window (seconds): {args.window_seconds}")
    print(f"Score key: {args.score_key}")
    print(f"AUC: {auc:.6f}")
    print(f"Curve PNG: {output_png}")
    print(f"Points CSV: {output_csv}")
    print(f"Summary JSON: {output_json}")


if __name__ == "__main__":
    main()
