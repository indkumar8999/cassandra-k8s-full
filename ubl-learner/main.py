import json
import math
import os
import threading
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


import numpy as np
import requests
from flask import Flask, jsonify, request
from sklearn.model_selection import KFold


app = Flask(__name__)


def _to_builtin(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: _to_builtin(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    if isinstance(value, tuple):
        return [_to_builtin(item) for item in value]
    return value


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


PROMETHEUS_BASE = os.getenv("PROMETHEUS_BASE", "http://prometheus-operated.monitoring.svc.cluster.local:9090")
POLL_SEC = _env_float("POLL_SEC", 2.0)
BOOTSTRAP_SAMPLES = _env_int("BOOTSTRAP_SAMPLES", 300)
SOM_ROWS = _env_int("SOM_ROWS", 32)
SOM_COLS = _env_int("SOM_COLS", 32)
SOM_LR = _env_float("SOM_LR", 0.7)
SOM_SIGMA = _env_float("SOM_SIGMA", 4.0)
TRAIN_EPOCHS = _env_int("TRAIN_EPOCHS", 10)
THRESHOLD_PERCENTILE = _env_float("THRESHOLD_PERCENTILE", 85.0)
ANOMALY_STREAK = _env_int("ANOMALY_STREAK", 3)
SMOOTH_K = _env_int("SMOOTH_K", 5)
CAUSE_Q = _env_int("CAUSE_Q", 5)
ONLINE_UPDATE_ENABLED = os.getenv("ONLINE_UPDATE_ENABLED", "1") == "1"
MAX_SCORE_STREAM = _env_int("MAX_SCORE_STREAM", 5000)
MAX_ALARMS = _env_int("MAX_ALARMS", 1000)
TIER_B_MIN_COVERAGE = _env_float("TIER_B_MIN_COVERAGE", 0.9)
TARGET_NAMESPACE = os.getenv("TARGET_NAMESPACE", "cassandra-lab")
CASSANDRA_PODS = [pod.strip() for pod in os.getenv("CASSANDRA_PODS", "cassandra-0,cassandra-1,cassandra-2").split(",") if pod.strip()]
PROM_QUERY_WORKERS = _env_int("PROM_QUERY_WORKERS", 12)
PROM_QUERY_TIMEOUT_SEC = _env_float("PROM_QUERY_TIMEOUT_SEC", 3.0)
THRESHOLD_RECALC_ENABLED = os.getenv("THRESHOLD_RECALC_ENABLED", "1") == "1"
THRESHOLD_RECALC_EVERY_UPDATES = _env_int("THRESHOLD_RECALC_EVERY_UPDATES", 25)

KNOWN_PHASES = ("normal", "load", "chaos", "cooldown")


TIER_A_NODE_QUERY_TEMPLATES = {
    "tier_a_cpu_usage_cores": 'sum(rate(container_cpu_usage_seconds_total{namespace="__NAMESPACE__",pod="__POD__"}[1m]))',
    "tier_a_memory_working_set_bytes": 'sum(container_memory_working_set_bytes{namespace="__NAMESPACE__",pod="__POD__"})',
    "tier_a_disk_read_bytes_per_sec": 'sum(rate(container_fs_reads_bytes_total{namespace="__NAMESPACE__",pod="__POD__"}[1m]))',
}



TIER_A_FEATURES = [
    "tier_a_cpu_usage_cores",
    "tier_a_memory_working_set_bytes",
    "tier_a_disk_read_bytes_per_sec",
]

# For averaging, define the base metric names (without pod suffix)
TIER_A_AVG_FEATURES = [
    "tier_a_cpu_usage_cores",
    "tier_a_memory_working_set_bytes",
    "tier_a_disk_read_bytes_per_sec",
]


@dataclass
class Sample:
    ts: float
    values: Dict[str, float]
    quality_valid: bool
    missing_required: List[str]
    missing_tier_b: List[str]


class SOM:
    def __init__(self, rows: int, cols: int, dims: int, lr: float, sigma: float, radius: int = 2):
        self.rows = rows
        self.cols = cols
        self.dims = dims
        self.lr = lr
        self.sigma = sigma
        self.radius = radius
        self.weights = np.random.uniform(0.0, 100.0, (rows, cols, dims))

    def bmu(self, vec: np.ndarray) -> Tuple[int, int]:
        dists = np.linalg.norm(self.weights - vec, axis=2)
        return np.unravel_index(np.argmin(dists), dists.shape)

    def train_step(self, vec: np.ndarray):
        bmu_r, bmu_c = self.bmu(vec)
        rr, cc = np.indices((self.rows, self.cols))
        dist2 = (rr - bmu_r) ** 2 + (cc - bmu_c) ** 2
        # Only update neurons within the defined radius
        mask = dist2 <= self.radius ** 2
        neighborhood = np.exp(-dist2 / (2.0 * (self.sigma ** 2))) * mask
        adjustment = self.lr * neighborhood[..., np.newaxis] * (vec - self.weights)
        self.weights += adjustment

    def train(self, data: np.ndarray, epochs: int):
        for _ in range(max(1, epochs)):
            np.random.shuffle(data)
            for vec in data:
                self.train_step(vec)

    def area_map(self) -> np.ndarray:
        area = np.zeros((self.rows, self.cols), dtype=np.float64)
        for r in range(self.rows):
            for c in range(self.cols):
                neighbors = []
                if r > 0:
                    neighbors.append((r - 1, c))
                if r < self.rows - 1:
                    neighbors.append((r + 1, c))
                if c > 0:
                    neighbors.append((r, c - 1))
                if c < self.cols - 1:
                    neighbors.append((r, c + 1))
                curr = self.weights[r, c]
                dist_sum = 0.0
                for nr, nc in neighbors:
                    dist_sum += np.abs(curr - self.weights[nr, nc]).sum()
                area[r, c] = dist_sum
        return area


class LearnerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "normal"
        self.ready = False
        self.trained = False
        self.bootstrap_samples: List[Sample] = []
        self.norm_max: Dict[str, float] = {}
        self.feature_order: List[str] = []
        self.som: Optional[SOM] = None
        self.area_map: Optional[np.ndarray] = None
        self.threshold: float = 0.0
        self.anomaly_streak = 0
        self.score_stream = deque(maxlen=MAX_SCORE_STREAM)
        self.alarms = deque(maxlen=MAX_ALARMS)
        self.last_error: Optional[str] = None
        self.training_duration_sec = 0.0
        self.training_start_ts: Optional[float] = None
        self.training_end_ts: Optional[float] = None
        self.total_samples_seen = 0
        self.total_samples_scored = 0
        self.score_latency_ms = deque(maxlen=MAX_SCORE_STREAM)
        self.bmu_hits = Counter()
        self.scored_by_phase = Counter()
        self.dropped_missing_tier_a = 0
        self.online_updates_since_threshold_refresh = 0
        self.query_pool = ThreadPoolExecutor(max_workers=max(1, PROM_QUERY_WORKERS))
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

    def _tier_a_feature_names(self) -> List[str]:
        # Return all per-pod feature names for completeness, but not used for input vector anymore
        names: List[str] = []
        for pod in CASSANDRA_PODS:
            for base in TIER_A_FEATURES:
                names.append(f"{base}__{pod}")
        return names

    def _avg_tier_a_features(self, sample: Sample) -> Dict[str, float]:
        # For each base metric, average across all pods
        avg_features = {}
        for base in TIER_A_AVG_FEATURES:
            vals = [sample.values.get(f"{base}__{pod}") for pod in CASSANDRA_PODS]
            vals = [v for v in vals if v is not None]
            avg_features[base] = float(np.mean(vals)) if vals else 0.0
        return avg_features

    def _query_prom(self, query: str) -> Optional[float]:
        try:
            response = requests.get(
                f"{PROMETHEUS_BASE}/api/v1/query",
                params={"query": query},
                timeout=PROM_QUERY_TIMEOUT_SEC,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "success":
                return None
            result = payload.get("data", {}).get("result", [])
            if not result:
                return None
            return float(result[0]["value"][1])
        except Exception:
            return None

    def _collect_sample(self) -> Sample:
        values: Dict[str, float] = {}
        required_missing: List[str] = []

        query_jobs = []
        for pod in CASSANDRA_PODS:
            for base_name, template in TIER_A_NODE_QUERY_TEMPLATES.items():
                key = f"{base_name}__{pod}"
                promql = template.replace("__NAMESPACE__", TARGET_NAMESPACE).replace("__POD__", pod)
                query_jobs.append((key, promql, True))

        future_to_meta = {
            self.query_pool.submit(self._query_prom, promql): (key, required)
            for key, promql, required in query_jobs
        }
        for future in as_completed(future_to_meta):
            key, required = future_to_meta[future]
            value = future.result()
            if value is None or math.isnan(value) or math.isinf(value):
                if required:
                    required_missing.append(key)
                continue
            values[key] = value

        return Sample(
            ts=time.time(),
            values=values,
            quality_valid=len(required_missing) == 0,
            missing_required=required_missing,
            missing_tier_b=[],
        )

    def _moving_avg(self, history: List[np.ndarray], vec: np.ndarray) -> np.ndarray:
        if SMOOTH_K <= 1:
            return vec
        history.append(vec)
        window = history[-SMOOTH_K:]
        return np.mean(window, axis=0)

    def _normalize_vector(self, sample: Sample) -> Tuple[np.ndarray, List[str]]:
        # Use only the average value for each metric
        avg_features = self._avg_tier_a_features(sample)
        missing_required = [k for k, v in avg_features.items() if v == 0.0]
        if missing_required:
            return np.array([]), missing_required

        raw_values = [avg_features[feature] for feature in TIER_A_AVG_FEATURES]
        raw = np.array(raw_values, dtype=np.float64)
        if not self.norm_max:
            return raw, []

        denom = np.array([max(self.norm_max[f], 1e-9) for f in TIER_A_AVG_FEATURES], dtype=np.float64)
        normed = (raw / denom) * 100.0
        return normed, []

    def _apply_training_smoothing(self, data: np.ndarray) -> np.ndarray:
        if SMOOTH_K <= 1 or len(data) <= 1:
            return data
        smoothed = []
        for idx in range(len(data)):
            lo = max(0, idx - SMOOTH_K + 1)
            smoothed.append(np.mean(data[lo : idx + 1], axis=0))
        return np.array(smoothed, dtype=np.float64)

    def _refresh_threshold(self):
        if self.area_map is None:
            return
        self.threshold = float(np.percentile(self.area_map.flatten(), THRESHOLD_PERCENTILE))

    def _cause_ranking(self, bmu_r: int, bmu_c: int) -> List[str]:
        if self.area_map is None or self.som is None:
            return []
        max_radius = max(self.som.rows, self.som.cols)
        normal_neighbors: List[Tuple[int, int]] = []

        for radius in range(1, max_radius + 1):
            for r in range(max(0, bmu_r - radius), min(self.som.rows, bmu_r + radius + 1)):
                for c in range(max(0, bmu_c - radius), min(self.som.cols, bmu_c + radius + 1)):
                    if abs(r - bmu_r) + abs(c - bmu_c) > radius:
                        continue
                    if self.area_map[r, c] < self.threshold:
                        normal_neighbors.append((r, c))
                    if len(normal_neighbors) >= CAUSE_Q:
                        break
                if len(normal_neighbors) >= CAUSE_Q:
                    break
            if len(normal_neighbors) >= CAUSE_Q:
                break

        if not normal_neighbors:
            return []

        anomaly_vec = self.som.weights[bmu_r, bmu_c]
        votes = Counter()
        for nr, nc in normal_neighbors:
            diffs = np.abs(anomaly_vec - self.som.weights[nr, nc])
            top_idx = int(np.argmax(diffs))
            votes[self.feature_order[top_idx]] += 1

        return [name for name, _ in votes.most_common()]

    def _train(self):
        valid = [s for s in self.bootstrap_samples if s.quality_valid]
        if len(valid) < BOOTSTRAP_SAMPLES:
            return

        self.training_start_ts = time.time()
        self.feature_order = TIER_A_AVG_FEATURES.copy()
        train_rows = []
        for sample in valid:
            avg_features = self._avg_tier_a_features(sample)
            if any(avg_features[k] == 0.0 for k in TIER_A_AVG_FEATURES):
                continue
            train_rows.append(np.array([avg_features[feature] for feature in TIER_A_AVG_FEATURES], dtype=np.float64))

        if not train_rows:
            self.last_error = "No complete vectors available for training."
            return

        train_data = np.array(train_rows)
        train_data = self._apply_training_smoothing(train_data)
        self.norm_max = {name: float(max(train_data[:, idx].max(), 1e-9)) for idx, name in enumerate(self.feature_order)}
        train_data_norm = (train_data / np.array([self.norm_max[f] for f in self.feature_order])) * 100.0

        # K-Fold Cross Validation (k=3) and best SOM selection by min sum of validation BMU areas
        k = 3
        kf = KFold(n_splits=k, shuffle=True, random_state=42)
        fold_metrics = []
        som_models = []
        for fold, (train_idx, test_idx) in enumerate(kf.split(train_data_norm)):
            X_train, X_val = train_data_norm[train_idx], train_data_norm[test_idx]
            som = SOM(SOM_ROWS, SOM_COLS, X_train.shape[1], SOM_LR, SOM_SIGMA, radius=2)
            som.train(X_train.copy(), TRAIN_EPOCHS)
            area_map = som.area_map()
            # For each validation sample, get BMU and area value
            val_areas = []
            for vec in X_val:
                bmu_r, bmu_c = som.bmu(vec)
                val_areas.append(area_map[bmu_r, bmu_c])
            sum_area = float(np.sum(val_areas)) if val_areas else float('inf')
            fold_metrics.append({
                "fold": fold+1,
                "sum_area": sum_area,
                "mean_area": float(np.mean(val_areas)) if val_areas else 0.0,
                "std_area": float(np.std(val_areas)) if val_areas else 0.0,
                "min_area": float(np.min(val_areas)) if val_areas else 0.0,
                "max_area": float(np.max(val_areas)) if val_areas else 0.0,
            })
            som_models.append({
                "model": som,
                "area_map": area_map,
                "sum_area": sum_area
            })

        self.kfold_metrics = fold_metrics
        # Select the SOM with the minimum sum_area on its validation set
        best_idx = int(np.argmin([m["sum_area"] for m in som_models]))
        best_som = som_models[best_idx]["model"]
        best_area_map = som_models[best_idx]["area_map"]
        self.som = best_som
        self.area_map = best_area_map
        self._refresh_threshold()
        self.trained = True
        self.ready = True
        self.training_end_ts = time.time()
        self.training_duration_sec = self.training_end_ts - self.training_start_ts

    def _record_alarm(self, payload: Dict):
        self.alarms.append(payload)

    def _score_sample(self, sample: Sample, smooth_history: List[np.ndarray]):
        if self.som is None or self.area_map is None:
            return

        start = time.perf_counter()
        vec, missing = self._normalize_vector(sample)
        if missing:
            tier_a_set = set(self._tier_a_feature_names())
            if any(name in tier_a_set for name in missing):
                self.dropped_missing_tier_a += 1
            return

        vec = self._moving_avg(smooth_history, vec)
        bmu_r, bmu_c = self.som.bmu(vec)
        area_value = float(self.area_map[bmu_r, bmu_c])
        is_anomaly = area_value >= self.threshold
        self.anomaly_streak = self.anomaly_streak + 1 if is_anomaly else 0
        causes = self._cause_ranking(bmu_r, bmu_c) if is_anomaly else []
        if ONLINE_UPDATE_ENABLED and self.phase != "chaos":
            self.som.train_step(vec)
            self.area_map = self.som.area_map()
            if THRESHOLD_RECALC_ENABLED:
                self.online_updates_since_threshold_refresh += 1
                if self.online_updates_since_threshold_refresh >= max(1, THRESHOLD_RECALC_EVERY_UPDATES):
                    self._refresh_threshold()
                    self.online_updates_since_threshold_refresh = 0

        score_latency = (time.perf_counter() - start) * 1000.0
        self.score_latency_ms.append(score_latency)
        self.total_samples_scored += 1
        self.scored_by_phase[self.phase] += 1
        self.bmu_hits[f"{bmu_r},{bmu_c}"] += 1

        event = {
            "ts": sample.ts,
            "phase": self.phase,
            "score_area": area_value,
            "threshold": self.threshold,
            "is_anomaly": is_anomaly,
            "streak": self.anomaly_streak,
            "bmu": [bmu_r, bmu_c],
            "causes": causes,
            "quality_valid": sample.quality_valid,
            "missing_required": sample.missing_required,
            "missing_tier_b": sample.missing_tier_b,
            "score_latency_ms": round(score_latency, 3),
        }
        self.score_stream.append(event)
        if self.anomaly_streak >= ANOMALY_STREAK:
            self._record_alarm(
                {
                    "ts": sample.ts,
                    "phase": self.phase,
                    "score_area": area_value,
                    "threshold": self.threshold,
                    "bmu": [bmu_r, bmu_c],
                    "causes": causes,
                    "streak": self.anomaly_streak,
                }
            )

    def _poll_loop(self):
        smooth_history: List[np.ndarray] = []
        while self.running:
            with self.lock:
                try:
                    sample = self._collect_sample()
                    self.total_samples_seen += 1
                    if not self.trained:
                        self.bootstrap_samples.append(sample)
                        self._train()
                    elif sample.quality_valid:
                        self._score_sample(sample, smooth_history)
                    else:
                        self.dropped_missing_tier_a += 1
                except Exception as ex:
                    self.last_error = str(ex)
            time.sleep(POLL_SEC)

    def report(self) -> Dict:
        avg_score_latency = float(np.mean(self.score_latency_ms)) if self.score_latency_ms else 0.0
        bmu_coverage = len(self.bmu_hits)
        alarms = list(self.alarms)
        stream = list(self.score_stream)
        lead_times = []
        first_chaos_ts = None
        for item in stream:
            if item["phase"] == "chaos":
                first_chaos_ts = item["ts"]
                break
        if first_chaos_ts is not None:
            for alarm in alarms:
                if alarm["ts"] >= first_chaos_ts:
                    lead_times.append(alarm["ts"] - first_chaos_ts)

        report = {
            "trained": self.trained,
            "ready": self.ready,
            "phase": self.phase,
            "bootstrap_target_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_collected_samples": len(self.bootstrap_samples),
            "training_duration_sec": round(self.training_duration_sec, 3),
            "total_samples_seen": self.total_samples_seen,
            "total_samples_scored": self.total_samples_scored,
            "total_samples_dropped_missing_tier_a": self.dropped_missing_tier_a,
            "scored_by_phase": {phase: self.scored_by_phase.get(phase, 0) for phase in KNOWN_PHASES},
            "alarm_count": len(alarms),
            "score_stream_count": len(stream),
            "avg_score_latency_ms": round(avg_score_latency, 3),
            "bmu_coverage_count": bmu_coverage,
            "feature_order": self.feature_order,
            "threshold_percentile": THRESHOLD_PERCENTILE,
            "threshold_value": self.threshold,
            "lead_time_seconds": {
                "mean": round(float(np.mean(lead_times)), 3) if lead_times else None,
                "median": round(float(np.median(lead_times)), 3) if lead_times else None,
                "samples": len(lead_times),
            },
            "last_error": self.last_error,
        }
        # Add k-fold metrics if available
        if hasattr(self, "kfold_metrics"):
            report["kfold_metrics"] = self.kfold_metrics
        return report


state = LearnerState()


@app.get("/health")
def health():
    return jsonify({"status": "up"})


@app.get("/status")
def status():
    with state.lock:
        valid_bootstrap_samples = len([sample for sample in state.bootstrap_samples if sample.quality_valid])
        return jsonify(
            {
                "trained": state.trained,
                "ready": state.ready,
                "phase": state.phase,
                "bootstrap_collected_samples": len(state.bootstrap_samples),
                "bootstrap_valid_samples": valid_bootstrap_samples,
                "bootstrap_target_samples": BOOTSTRAP_SAMPLES,
                "training_duration_sec": round(state.training_duration_sec, 3),
                "threshold": state.threshold,
                "threshold_percentile": THRESHOLD_PERCENTILE,
                "total_samples_dropped_missing_tier_a": state.dropped_missing_tier_a,
                "total_samples_dropped_missing_tier_b": state.dropped_missing_tier_b,
                "last_error": state.last_error,
            }
        )


@app.post("/phase")
def set_phase():
    body = request.get_json(silent=True) or {}
    new_phase = body.get("phase", "").strip().lower()
    if new_phase not in {"normal", "load", "chaos", "cooldown"}:
        return jsonify({"error": "phase must be one of normal/load/chaos/cooldown"}), 400
    with state.lock:
        state.phase = new_phase
    return jsonify({"message": "phase updated", "phase": new_phase})


@app.get("/score-stream")
def score_stream():
    limit = int(request.args.get("limit", "200"))
    with state.lock:
        data = list(state.score_stream)[-limit:]
    return jsonify({"count": len(data), "items": _to_builtin(data)})


@app.get("/alarms")
def alarms():
    limit = int(request.args.get("limit", "200"))
    with state.lock:
        data = list(state.alarms)[-limit:]
    return jsonify({"count": len(data), "items": _to_builtin(data)})


@app.post("/reset")
def reset():
    with state.lock:
        state.phase = "normal"
        state.ready = False
        state.trained = False
        state.bootstrap_samples.clear()
        state.norm_max.clear()
        state.feature_order.clear()
        state.som = None
        state.area_map = None
        state.threshold = 0.0
        state.anomaly_streak = 0
        state.score_stream.clear()
        state.alarms.clear()
        state.last_error = None
        state.training_duration_sec = 0.0
        state.training_start_ts = None
        state.training_end_ts = None
        state.total_samples_seen = 0
        state.total_samples_scored = 0
        state.dropped_missing_tier_a = 0
        state.score_latency_ms.clear()
        state.bmu_hits.clear()
        state.scored_by_phase.clear()
        state.online_updates_since_threshold_refresh = 0
    return jsonify({"message": "learner reset"})


@app.get("/report")
def report():
    with state.lock:
        return jsonify(_to_builtin(state.report()))


@app.get("/config")
def config():
    tier_a_feature_count = len(TIER_A_FEATURES) * len(CASSANDRA_PODS)
    return jsonify(
        {
            "prometheus_base": PROMETHEUS_BASE,
            "target_namespace": TARGET_NAMESPACE,
            "cassandra_pods": CASSANDRA_PODS,
            "poll_sec": POLL_SEC,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "som_rows": SOM_ROWS,
            "som_cols": SOM_COLS,
            "som_lr": SOM_LR,
            "som_sigma": SOM_SIGMA,
            "train_epochs": TRAIN_EPOCHS,
            "threshold_percentile": THRESHOLD_PERCENTILE,
            "anomaly_streak": ANOMALY_STREAK,
            "smooth_k": SMOOTH_K,
            "cause_q": CAUSE_Q,
            "online_update_enabled": ONLINE_UPDATE_ENABLED,
            "threshold_recalc_enabled": THRESHOLD_RECALC_ENABLED,
            "threshold_recalc_every_updates": THRESHOLD_RECALC_EVERY_UPDATES,
            "prom_query_workers": PROM_QUERY_WORKERS,
            "prom_query_timeout_sec": PROM_QUERY_TIMEOUT_SEC,
            "tier_a_features": TIER_A_FEATURES,
            "tier_a_feature_count": tier_a_feature_count,
        }
    )


def main():
    app.run(host="0.0.0.0", port=8100, threaded=True)


if __name__ == "__main__":
    main()
