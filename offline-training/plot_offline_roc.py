#!/usr/bin/env python3
"""
Plot ROC curves from run_offline_inference.py output JSON.

Input: artifacts/offline_inference_*_with_eval.json
Output: PNG saved under artifacts/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _roc_points(obj: Dict[str, Any], key: str) -> List[Dict[str, float]]:
    eval_obj = obj.get("evaluation") or {}
    roc_obj = (eval_obj.get("roc") or {}).get(key) or {}
    pts = roc_obj.get("points") or []
    return [p for p in pts if isinstance(p, dict) and "fpr" in p and "tpr" in p]


def _as_xy(points: List[Dict[str, float]]) -> Tuple[List[float], List[float]]:
    # Ensure monotonic-ish ordering for plotting: sort by FPR then TPR.
    pts = sorted(points, key=lambda p: (float(p["fpr"]), float(p["tpr"])))
    xs = [float(p["fpr"]) for p in pts]
    ys = [float(p["tpr"]) for p in pts]
    return xs, ys


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot ROC curves from offline inference output JSON")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("artifacts/offline_inference_cpu_test_with_eval.json"),
        help="Output JSON produced by run_offline_inference.py",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/offline_inference_cpu_test_roc.png"),
        help="PNG path to write",
    )
    parser.add_argument("--title", type=str, default="CPU Hog ROC (pending window W=10s)", help="Plot title")
    args = parser.parse_args()

    data = _load(args.input)
    if not (data.get("evaluation") and (data["evaluation"].get("roc") or {})):
        raise SystemExit("No evaluation.roc found in input JSON (did you collect SLO + run inference with eval?)")

    # Lazy import so the script can still be inspected without matplotlib.
    import matplotlib.pyplot as plt  # type: ignore

    series = [
        ("ubl_5pts", "UBL-5PtS"),
        ("ubl_ns", "UBL-NS"),
        ("knn", "k-NN"),
    ]

    plt.figure(figsize=(6.5, 5.5), dpi=160)
    for key, label in series:
        pts = _roc_points(data, key)
        if not pts:
            continue
        x, y = _as_xy(pts)
        plt.plot([v * 100.0 for v in x], [v * 100.0 for v in y], linewidth=2.0, label=label)

    plt.xlim(0, 100)
    plt.ylim(0, 100)
    plt.xlabel("False Positive Rate (%)")
    plt.ylabel("True Positive Rate (%)")
    plt.title(args.title)
    plt.grid(True, alpha=0.25)
    plt.legend(loc="lower right")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(args.output)
    print(f"[OK] Wrote ROC plot to {args.output}")


if __name__ == "__main__":
    main()

