#!/usr/bin/env python3
"""
Plot ROC curves from run_offline_inference.py output JSON.

Input: artifacts/offline_inference_*_with_eval.json
Output: PNG saved under artifacts/
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


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


def _confusion(pred: Sequence[bool], truth: Sequence[bool]) -> Tuple[int, int, int, int]:
    tp = fp = tn = fn = 0
    for p, t in zip(pred, truth):
        if p and t:
            tp += 1
        elif p and not t:
            fp += 1
        elif (not p) and (not t):
            tn += 1
        else:
            fn += 1
    return tp, fp, tn, fn


def _roc_from_scores(scores: List[float], truth: List[bool], max_points: int = 200) -> List[Dict[str, float]]:
    if not scores or len(scores) != len(truth):
        return []
    uniq = sorted(set(float(s) for s in scores))
    if not uniq:
        return []

    # Sample thresholds over unique score values (more stable than linspace for repeated scores).
    if len(uniq) <= max(2, int(max_points)):
        thresholds = uniq
    else:
        step = (len(uniq) - 1) / float(max_points - 1)
        thresholds = [uniq[int(round(i * step))] for i in range(int(max_points))]
        thresholds = sorted(set(thresholds))

    pts: List[Dict[str, float]] = []
    for thr in thresholds:
        pred = [float(s) >= float(thr) for s in scores]
        tp, fp, tn, fn = _confusion(pred, truth)
        tpr = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
        pts.append({"threshold": float(thr), "tpr": float(tpr), "fpr": float(fpr)})

    # Deduplicate identical points to keep plotting clean.
    seen = set()
    out: List[Dict[str, float]] = []
    for p in sorted(pts, key=lambda d: (float(d["fpr"]), float(d["tpr"]))):
        key = (round(float(p["fpr"]), 12), round(float(p["tpr"]), 12))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)

    # Ensure the curve visually connects to the origin.
    # Some threshold samplings may not produce an explicit (0,0) point if no threshold
    # yields zero predicted positives; adding it makes the plot consistent.
    out.append({"threshold": float("inf"), "tpr": 0.0, "fpr": 0.0})
    out.append({"threshold": float("-inf"), "tpr": 1.0, "fpr": 1.0})
    out = sorted(
        {(round(float(p["fpr"]), 12), round(float(p["tpr"]), 12)): p for p in out}.values(),
        key=lambda d: (float(d["fpr"]), float(d["tpr"])),
    )
    return out


def _load_scores_csv(path: Path) -> Tuple[List[float], List[bool]]:
    """
    Expected columns: ts,label,score where label is 0/1 and score is float.
    """
    scores: List[float] = []
    truth: List[bool] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            if not isinstance(row, dict):
                continue
            lbl = row.get("label")
            sc = row.get("score")
            if lbl is None or sc is None:
                continue
            try:
                truth.append(bool(int(str(lbl).strip())))
                scores.append(float(str(sc).strip()))
            except Exception:
                continue
    return scores, truth


def _auc_from_points(points: List[Dict[str, float]]) -> Optional[float]:
    xy: List[Tuple[float, float]] = []
    for p in points:
        if not isinstance(p, dict):
            continue
        if "fpr" not in p or "tpr" not in p:
            continue
        xy.append((float(p["fpr"]), float(p["tpr"])))
    if not xy:
        return None
    xy.append((0.0, 0.0))
    xy.append((1.0, 1.0))
    xy = sorted(set(xy), key=lambda t: (t[0], t[1]))
    auc = 0.0
    for (x0, y0), (x1, y1) in zip(xy[:-1], xy[1:]):
        dx = max(0.0, float(x1 - x0))
        auc += dx * (float(y0) + float(y1)) / 2.0
    return float(max(0.0, min(1.0, auc)))


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
    parser.add_argument(
        "--ubl-5pts-scores-csv",
        type=Path,
        default=None,
        help="Optional CSV (ts,label,score) to use for the UBL-5PtS curve instead of evaluation.roc.ubl_5pts",
    )
    parser.add_argument(
        "--csv-roc-points",
        type=int,
        default=200,
        help="Max ROC points to compute from --ubl-5pts-scores-csv (default: 200)",
    )
    parser.add_argument(
        "--ubl-5pts-label",
        type=str,
        default=None,
        help="Optional label override for the UBL-5PtS series",
    )
    args = parser.parse_args()

    data = _load(args.input)
    if not (data.get("evaluation") and (data["evaluation"].get("roc") or {})):
        raise SystemExit("No evaluation.roc found in input JSON (did you collect SLO + run inference with eval?)")

    # Lazy import so the script can still be inspected without matplotlib.
    import matplotlib.pyplot as plt  # type: ignore

    # Build the series list dynamically so UBL-5PtS can be overridden from a CSV.
    series: List[Tuple[str, str, Optional[List[Dict[str, float]]]]] = []
    if args.ubl_5pts_scores_csv is not None:
        csv_scores, csv_truth = _load_scores_csv(args.ubl_5pts_scores_csv)
        pts = _roc_from_scores(csv_scores, csv_truth, max_points=int(args.csv_roc_points))
        label = args.ubl_5pts_label or "UBL-5PtS"
        series.append(("ubl_5pts", label, pts))
    else:
        series.append(("ubl_5pts", "UBL-5PtS", None))
    series.extend([("ubl_ns", "UBL-NS", None)])

    plt.figure(figsize=(6.5, 5.5), dpi=160)
    # Baseline (random classifier)
    plt.plot([0, 100], [0, 100], linestyle="--", linewidth=1.4, color="0.55", label="x=y (random)")
    for key, label, override_pts in series:
        pts = override_pts if override_pts is not None else _roc_points(data, key)
        if not pts:
            continue
        auc = _auc_from_points(pts)
        auc_s = "" if auc is None else f" (AUC={auc:.3f})"
        x, y = _as_xy(pts)
        plt.plot([v * 100.0 for v in x], [v * 100.0 for v in y], linewidth=2.0, label=f"{label}{auc_s}")

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

