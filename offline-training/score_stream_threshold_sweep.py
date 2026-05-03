#!/usr/bin/env python3
"""
Add percentile-based thresholds (80/85/90) to a score_stream.json and compute confusion metrics.

Thresholds are derived from a SOM snapshot's `area_map`:
  thr_p = percentile(area_map.flatten(), p)

Then each score_stream item gets:
  - threshold_p80 / threshold_p85 / threshold_p90
  - diagnosis_p80 / diagnosis_p85 / diagnosis_p90  (abnormal if score_area >= thr_px)
  - is_anomaly_p80 / is_anomaly_p85 / is_anomaly_p90
  - alarm_fired_p80 / alarm_fired_p85 / alarm_fired_p90 (true if k consecutive anomalies)

Finally writes summary confusion metrics vs `slo_violated`:
  TP/FP/TN/FN + accuracy + tpr + fpr for each threshold.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compute_thresholds_from_snapshot(snapshot_path: Path, percentiles: List[float]) -> Dict[float, float]:
    snap = load_json(snapshot_path)
    if "area_map" not in snap:
        raise ValueError("snapshot missing 'area_map'")
    area = np.asarray(snap["area_map"], dtype=np.float64).flatten()
    if area.size == 0:
        raise ValueError("snapshot area_map empty")
    out: Dict[float, float] = {}
    for p in percentiles:
        out[float(p)] = float(np.percentile(area, float(p)))
    return out


def confusion_for_threshold(items: List[Dict[str, Any]], pred_key: str) -> Dict[str, float]:
    tp = fp = tn = fn = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        pred = bool(it.get(pred_key) is True)
        truth = bool(it.get("slo_violated") is True)
        if pred and truth:
            tp += 1
        elif pred and (not truth):
            fp += 1
        elif (not pred) and (not truth):
            tn += 1
        else:
            fn += 1
    total = tp + fp + tn + fn
    acc = (tp + tn) / total if total else 0.0
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "tp": float(tp),
        "fp": float(fp),
        "tn": float(tn),
        "fn": float(fn),
        "accuracy": float(acc),
        "tpr": float(tpr),
        "fpr": float(fpr),
        "total": float(total),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Add p80/p85/p90 thresholds + diagnoses to score_stream.json")
    ap.add_argument(
        "--som-snapshot",
        type=Path,
        default=Path("../ubl-learner/som_trained_snapshot.json"),
        help="Path to SOM snapshot JSON (must contain area_map)",
    )
    ap.add_argument(
        "--input",
        type=Path,
        default=Path("../artifacts/scenario-nb-1777232932/score_stream.json"),
        help="Input score_stream.json",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("../artifacts/scenario-nb-1777232932/score_stream_with_thresholds.json"),
        help="Output JSON path",
    )
    ap.add_argument(
        "--alarm-streak",
        type=int,
        default=5,
        help="k consecutive anomalies required to fire an alarm (default: 5)",
    )
    args = ap.parse_args()

    percentiles = [80.0, 85.0, 90.0]
    thresholds = compute_thresholds_from_snapshot(args.som_snapshot, percentiles)

    obj = load_json(args.input)
    items = obj.get("items") if isinstance(obj.get("items"), list) else []
    items = [it for it in items if isinstance(it, dict)]

    # First pass: per-item anomaly booleans per threshold.
    for it in items:
        score = it.get("score_area")
        if not isinstance(score, (int, float)):
            continue
        for p in percentiles:
            thr = float(thresholds[float(p)])
            key_thr = f"threshold_p{int(p)}"
            key_is = f"is_anomaly_p{int(p)}"
            key_diag = f"diagnosis_p{int(p)}"
            is_anom = bool(float(score) >= thr)
            it[key_thr] = thr
            it[key_is] = is_anom
            it[key_diag] = "abnormal" if is_anom else "normal"

    # Second pass: compute alarm firing (k consecutive anomalies) per threshold.
    k = max(1, int(args.alarm_streak))
    for p in percentiles:
        key_is = f"is_anomaly_p{int(p)}"
        key_alarm = f"alarm_fired_p{int(p)}"
        streak = 0
        for it in items:
            is_anom = bool(it.get(key_is) is True)
            streak = streak + 1 if is_anom else 0
            it[key_alarm] = bool(streak >= k)

    # Confusion is computed using alarm_fired (streak-gated), not raw is_anomaly.
    summary = {f"p{int(p)}": confusion_for_threshold(items, f"alarm_fired_p{int(p)}") for p in percentiles}

    out = dict(obj)
    out["threshold_sweep"] = {
        "som_snapshot": str(args.som_snapshot),
        "alarm_streak": int(args.alarm_streak),
        "thresholds": {f"p{int(p)}": float(thresholds[float(p)]) for p in percentiles},
        "confusion_vs_slo_violated": summary,
    }
    out["items"] = items

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[OK] wrote {args.output}")
    print(json.dumps(out["threshold_sweep"], indent=2))


if __name__ == "__main__":
    main()

