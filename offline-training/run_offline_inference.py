#!/usr/bin/env python3
"""
Offline inference on a saved Prometheus samples JSON.

Scores each tick with:
- UBL (pretrained SOM): no smoothing (NS) and k-point moving average on normalized vectors (5PtS)
- kNN (pretrained snapshot): k-th NN distance vs ref_vectors, compare to tau

Uses each snapshot's own norm_max for vector scaling (matches how each model was trained).
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

TIER_A_AVG_FEATURES = [
    "tier_a_cpu_usage_cores",
    "tier_a_memory_working_set_bytes",
    "tier_a_disk_io_bytes_per_sec",
]


def load_samples_json(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("samples"), list):
        return [x for x in payload["samples"] if isinstance(x, dict)]
    raise ValueError("Expected list or object with 'samples' list")


def avg_features(values: Dict[str, float], pods: List[str]) -> np.ndarray:
    out = []
    for base in TIER_A_AVG_FEATURES:
        vals = [values.get(f"{base}__{pod}") for pod in pods]
        vals = [float(v) for v in vals if v is not None and isinstance(v, (int, float))]
        out.append(float(np.mean(vals)) if vals else 0.0)
    return np.array(out, dtype=np.float64)


def normalize(raw: np.ndarray, norm_max: Dict[str, float], keys: List[str]) -> np.ndarray:
    denom = np.array([max(float(norm_max[k]), 1e-9) for k in keys], dtype=np.float64)
    return (raw / denom) * 100.0


def load_som_snapshot(path: Path) -> Tuple[np.ndarray, np.ndarray, float, Dict[str, float], List[str]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows = int(data["som_rows"])
    cols = int(data["som_cols"])
    feature_order = list(data["feature_order"])
    if feature_order != TIER_A_AVG_FEATURES:
        raise ValueError(f"SOM feature_order mismatch: {feature_order}")
    weights = np.asarray(data["weights"], dtype=np.float64)
    if weights.shape != (rows, cols, len(feature_order)):
        raise ValueError(f"SOM weights shape {weights.shape}, expected {(rows, cols, len(feature_order))}")
    area_map = np.asarray(data["area_map"], dtype=np.float64)
    if area_map.shape != (rows, cols):
        raise ValueError(f"SOM area_map shape {area_map.shape}")
    threshold = float(data["threshold"])
    norm_max = {str(k): float(v) for k, v in data["norm_max"].items()}
    return weights, area_map, threshold, norm_max, feature_order


def som_bmu(weights: np.ndarray, vec: np.ndarray) -> Tuple[int, int]:
    dists = np.linalg.norm(weights - vec, axis=2)
    return tuple(int(x) for x in np.unravel_index(int(np.argmin(dists)), dists.shape))


def load_knn_snapshot(path: Path) -> Tuple[np.ndarray, int, float, float, Dict[str, float]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    feature_order = list(data["feature_order"])
    if feature_order != TIER_A_AVG_FEATURES:
        raise ValueError(f"kNN feature_order mismatch: {feature_order}")
    k = int(data["k"])
    tau = float(data["tau"])
    tau_pct = float(data.get("tau_percentile", 95.0))
    ref = np.asarray(data["ref_vectors"], dtype=np.float64)
    if ref.ndim != 2 or ref.shape[1] != len(TIER_A_AVG_FEATURES):
        raise ValueError(f"kNN ref_vectors shape {ref.shape}")
    norm_max = {str(kk): float(vv) for kk, vv in (data.get("norm_max") or {}).items()}
    return ref, k, tau, tau_pct, norm_max


def knn_score(x: np.ndarray, X_ref: np.ndarray, k: int) -> float:
    d = np.linalg.norm(X_ref - x.reshape(1, -1), axis=1)
    n = int(d.shape[0])
    kk = min(max(1, int(k)), n)
    return float(np.partition(d, kk - 1)[kk - 1])


def moving_avg(history: deque, vec: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return vec
    history.append(vec.copy())
    window = list(history)[-k:]
    return np.mean(np.stack(window, axis=0), axis=0)


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def build_pending_truth(
    ts_list: List[float],
    slo_violated_list: List[bool],
    pending_window_sec: float,
) -> List[bool]:
    """
    Paper semantics:
      alert at t1 is a TP if SLO violation occurs at t2, with t1 < t2 <= t1 + W.

    For ROC, we convert this into a per-tick binary label:
      y_true_pending[tick i] = True if there exists a violation in (ts_i, ts_i + W].
    """
    n = len(ts_list)
    violated = np.array([bool(x) for x in slo_violated_list], dtype=np.int64)
    prefix = np.zeros(n + 1, dtype=np.int64)
    prefix[1:] = np.cumsum(violated)

    pending: List[bool] = [False] * n
    j_end = 0
    for i in range(n):
        if j_end < i + 1:
            j_end = i + 1
        end_ts = float(ts_list[i]) + float(pending_window_sec)
        while j_end < n and float(ts_list[j_end]) <= end_ts:
            j_end += 1
        # violations strictly after i, up to and including window end
        count = int(prefix[j_end] - prefix[i + 1])
        pending[i] = count > 0
    return pending


def roc_from_scores(
    scores: List[float],
    y_true: List[bool],
    points: int = 200,
) -> Dict[str, Any]:
    s = np.asarray(scores, dtype=np.float64)
    y = np.asarray([1 if b else 0 for b in y_true], dtype=np.int64)
    if s.size == 0 or y.size == 0 or s.size != y.size:
        return {"points": [], "note": "no data"}

    s_min = float(np.min(s))
    s_max = float(np.max(s))
    if s_min == s_max:
        thresholds = np.array([s_min], dtype=np.float64)
    else:
        thresholds = np.linspace(s_min, s_max, num=max(2, int(points)), dtype=np.float64)

    out_pts: List[Dict[str, Any]] = []
    for thr in thresholds:
        pred = (s >= float(thr)).astype(np.int64)
        tp = int(np.sum((pred == 1) & (y == 1)))
        fp = int(np.sum((pred == 1) & (y == 0)))
        tn = int(np.sum((pred == 0) & (y == 0)))
        fn = int(np.sum((pred == 0) & (y == 1)))
        tpr = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
        out_pts.append(
            {
                "threshold": float(thr),
                "tpr": tpr,
                "fpr": fpr,
                "Ntp": tp,
                "Nfp": fp,
                "Ntn": tn,
                "Nfn": fn,
            }
        )
    return {"points": out_pts, "score_min": s_min, "score_max": s_max}


def lead_times_for_threshold(
    ts_list: List[float],
    violation_ts_list: List[float],
    scores: List[float],
    threshold: float,
    pending_window_sec: float,
) -> Dict[str, Any]:
    """
    For each tick i where score[i] >= threshold, if there is a violation within (ts_i, ts_i+W],
    record the lead time (t2 - t1) where t2 is the earliest such violation timestamp.
    """
    leads: List[float] = []
    if not violation_ts_list:
        return {"count": 0, "lead_times_sec": [], "p50": None, "p90": None, "mean": None}

    for ts_i, score in zip(ts_list, scores):
        if float(score) < float(threshold):
            continue
        idx = bisect.bisect_right(violation_ts_list, float(ts_i))
        if idx >= len(violation_ts_list):
            continue
        t2 = float(violation_ts_list[idx])
        if t2 <= float(ts_i) + float(pending_window_sec):
            leads.append(float(t2 - float(ts_i)))

    if not leads:
        return {"count": 0, "lead_times_sec": [], "p50": None, "p90": None, "mean": None}

    arr = np.asarray(leads, dtype=np.float64)
    return {
        "count": int(arr.size),
        "lead_times_sec": [float(x) for x in leads],
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "mean": float(np.mean(arr)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline UBL + kNN inference on samples JSON")
    parser.add_argument(
        "--samples-json",
        type=Path,
        default=Path("artifacts/prometheus_samples_cpu_test.json"),
        help="Path to samples JSON (list or {samples: [...]})",
    )
    parser.add_argument(
        "--som-snapshot",
        type=Path,
        default=Path("../ubl-learner/som_trained_snapshot.json"),
        help="Pretrained SOM snapshot JSON",
    )
    parser.add_argument(
        "--knn-snapshot",
        type=Path,
        default=Path("../ubl-learner/knn_trained_snapshot.json"),
        help="Pretrained kNN snapshot JSON",
    )
    parser.add_argument(
        "--pods",
        type=str,
        default="cassandra-0,cassandra-1,cassandra-2",
        help="Comma-separated pod names used in metric keys",
    )
    parser.add_argument("--ubl-smooth-k", type=int, default=5, help="Moving-average window for UBL-5PtS scoring")
    parser.add_argument(
        "--pending-window-sec",
        type=float,
        default=10.0,
        help="Upper-bound anomaly pending time W (seconds) for ROC / lead-time evaluation (default: 10s)",
    )
    parser.add_argument(
        "--roc-points",
        type=int,
        default=200,
        help="Number of ROC threshold samples per model (default: 200)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/offline_inference_cpu_test.json"),
        help="Output JSON path (list of per-tick results)",
    )
    args = parser.parse_args()

    pods = [p.strip() for p in args.pods.split(",") if p.strip()]
    samples = load_samples_json(args.samples_json)
    if not samples:
        print("[ERROR] No samples", file=sys.stderr)
        sys.exit(1)

    weights, area_map, som_threshold, som_norm_max, _fo = load_som_snapshot(args.som_snapshot)
    X_ref, knn_k, knn_tau, knn_tau_pct, knn_norm_max = load_knn_snapshot(args.knn_snapshot)

    history_5: deque = deque(maxlen=max(1, int(args.ubl_smooth_k)))

    rows_out: List[Dict[str, Any]] = []
    ts_list: List[float] = []
    slo_violated_list: List[bool] = []
    ubl_ns_scores: List[float] = []
    ubl_5_scores: List[float] = []
    knn_scores: List[float] = []

    for rec in samples:
        values = rec.get("values") if isinstance(rec.get("values"), dict) else rec
        if not isinstance(values, dict):
            continue
        vals_f = {k: float(v) for k, v in values.items() if isinstance(v, (int, float))}
        raw = avg_features(vals_f, pods)
        vec_som = normalize(raw, som_norm_max, TIER_A_AVG_FEATURES)
        vec_knn = normalize(raw, knn_norm_max, TIER_A_AVG_FEATURES)

        vec_ns = vec_som.copy()
        vec_5 = moving_avg(history_5, vec_som, int(args.ubl_smooth_k))

        br, bc = som_bmu(weights, vec_ns)
        area_ns = float(area_map[br, bc])
        br5, bc5 = som_bmu(weights, vec_5)
        area_5 = float(area_map[br5, bc5])

        s_knn = knn_score(vec_knn, X_ref, knn_k)

        ts = _safe_float(rec.get("ts"))
        if ts is None:
            continue

        slo_obj = rec.get("slo") if isinstance(rec.get("slo"), dict) else None
        slo_violated = bool((slo_obj or {}).get("slo_violated", False)) if slo_obj is not None else False
        slo_p95 = _safe_float((slo_obj or {}).get("p95_ms")) if slo_obj is not None else None
        slo_p99 = _safe_float((slo_obj or {}).get("p99_ms")) if slo_obj is not None else None
        slo_thr = _safe_float((slo_obj or {}).get("threshold_ms")) if slo_obj is not None else None

        ts_list.append(float(ts))
        slo_violated_list.append(bool(slo_violated))
        ubl_ns_scores.append(float(area_ns))
        ubl_5_scores.append(float(area_5))
        knn_scores.append(float(s_knn))

        rows_out.append(
            {
                "tick_index": rec.get("tick_index"),
                "ts": float(ts),
                "input_vector_som_norm": vec_som.tolist(),
                "input_vector_knn_norm": vec_knn.tolist(),
                "slo": (
                    None
                    if slo_obj is None
                    else {
                        "p95_ms": slo_p95,
                        "p99_ms": slo_p99,
                        "threshold_ms": slo_thr,
                        "slo_violated": bool(slo_violated),
                    }
                ),
                "ubl_ns": {
                    "score_area": area_ns,
                    "threshold": som_threshold,
                    "is_anomaly": bool(area_ns >= som_threshold),
                    "bmu": [br, bc],
                },
                "ubl_5pts": {
                    "smooth_k": int(args.ubl_smooth_k),
                    "score_area": area_5,
                    "threshold": som_threshold,
                    "is_anomaly": bool(area_5 >= som_threshold),
                    "bmu": [br5, bc5],
                },
                "knn": {
                    "k": knn_k,
                    "tau": knn_tau,
                    "tau_percentile": knn_tau_pct,
                    "ref_size": int(X_ref.shape[0]),
                    "score_knn_kth": s_knn,
                    "is_anomaly": bool(s_knn >= knn_tau),
                },
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)

    evaluation: Optional[Dict[str, Any]] = None
    if any(slo_violated_list):
        pending_truth = build_pending_truth(ts_list, slo_violated_list, float(args.pending_window_sec))
        violation_ts_list = [ts for ts, v in zip(ts_list, slo_violated_list) if v]
        evaluation = {
            "pending_window_sec": float(args.pending_window_sec),
            "ground_truth": {
                "source": "slo.slo_violated",
                "violation_count": int(sum(1 for v in slo_violated_list if v)),
                "pending_positive_count": int(sum(1 for v in pending_truth if v)),
            },
            "roc": {
                "ubl_ns": roc_from_scores(ubl_ns_scores, pending_truth, points=int(args.roc_points)),
                "ubl_5pts": roc_from_scores(ubl_5_scores, pending_truth, points=int(args.roc_points)),
                "knn": roc_from_scores(knn_scores, pending_truth, points=int(args.roc_points)),
            },
            "lead_time": {
                "ubl_ns@som_threshold": lead_times_for_threshold(
                    ts_list, violation_ts_list, ubl_ns_scores, float(som_threshold), float(args.pending_window_sec)
                ),
                "ubl_5pts@som_threshold": lead_times_for_threshold(
                    ts_list, violation_ts_list, ubl_5_scores, float(som_threshold), float(args.pending_window_sec)
                ),
                "knn@tau": lead_times_for_threshold(
                    ts_list, violation_ts_list, knn_scores, float(knn_tau), float(args.pending_window_sec)
                ),
            },
        }

    payload = {
        "samples_source": str(args.samples_json),
        "som_snapshot": str(args.som_snapshot),
        "knn_snapshot": str(args.knn_snapshot),
        "count": len(rows_out),
        "items": rows_out,
        "evaluation": evaluation,
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[OK] Wrote {len(rows_out)} rows to {args.output}")


if __name__ == "__main__":
    main()
