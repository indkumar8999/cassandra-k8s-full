import json
import math
import os
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests
from flask import Flask, jsonify, request


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


TIER_A_NODE_QUERY_TEMPLATES = {
    "tier_a_cpu_usage_cores": 'sum(rate(container_cpu_usage_seconds_total{namespace="__NAMESPACE__",pod="__POD__"}[1m]))',
    "tier_a_memory_working_set_bytes": 'sum(container_memory_working_set_bytes{namespace="__NAMESPACE__",pod="__POD__"})',
    "tier_a_disk_read_bytes_per_sec": 'sum(rate(container_fs_reads_bytes_total{namespace="__NAMESPACE__",pod="__POD__"}[1m]))',
    "tier_a_disk_write_bytes_per_sec": 'sum(rate(container_fs_writes_bytes_total{namespace="__NAMESPACE__",pod="__POD__"}[1m]))',
    "tier_a_network_rx_bytes_per_sec": 'sum(rate(cassandra_metrics_count{namespace="__NAMESPACE__",pod="__POD__",type="ClientMessageSize",metric="BytesReceived"}[1m]))',
    "tier_a_network_tx_bytes_per_sec": 'sum(rate(cassandra_metrics_count{namespace="__NAMESPACE__",pod="__POD__",type="ClientMessageSize",metric="BytesSent"}[1m]))',
}

TIER_B_FEATURE_QUERIES = {
    "tier_b_simulator_write_latency_p95_ms": f'max(simulator_write_latency_p95_ms{{namespace="{TARGET_NAMESPACE}"}})',
    "tier_b_simulator_read_latency_p95_ms": f'max(simulator_read_latency_p95_ms{{namespace="{TARGET_NAMESPACE}"}})',
    "tier_b_simulator_writes_success_total": f'sum(simulator_writes_success_total{{namespace="{TARGET_NAMESPACE}"}})',
    "tier_b_simulator_reads_success_total": f'sum(simulator_reads_success_total{{namespace="{TARGET_NAMESPACE}"}})',
    "tier_b_jvm_heap_used_bytes": f'sum(jvm_memory_heap_used_bytes{{namespace="{TARGET_NAMESPACE}"}})',
    "tier_b_cassandra_client_request_count_per_sec": f'sum(rate(cassandra_metrics_count{{namespace="{TARGET_NAMESPACE}",type="ClientRequest"}}[1m]))',
}

TIER_A_FEATURES = [
    "tier_a_cpu_usage_cores",
    "tier_a_memory_working_set_bytes",
    "tier_a_disk_read_bytes_per_sec",
    "tier_a_disk_write_bytes_per_sec",
    "tier_a_network_rx_bytes_per_sec",
    "tier_a_network_tx_bytes_per_sec",
]


@dataclass
class Sample:
    ts: float
    values: Dict[str, float]
    quality_valid: bool
    missing: List[str]


class SOM:
    def __init__(self, rows: int, cols: int, dims: int, lr: float, sigma: float):
        self.rows = rows
        self.cols = cols
        self.dims = dims
        self.lr = lr
        self.sigma = sigma
        self.weights = np.random.uniform(0.0, 100.0, (rows, cols, dims))

    def bmu(self, vec: np.ndarray) -> Tuple[int, int]:
        dists = np.linalg.norm(self.weights - vec, axis=2)
        return np.unravel_index(np.argmin(dists), dists.shape)

    def train_step(self, vec: np.ndarray):
        bmu_r, bmu_c = self.bmu(vec)
        rr, cc = np.indices((self.rows, self.cols))
        dist2 = (rr - bmu_r) ** 2 + (cc - bmu_c) ** 2
        neighborhood = np.exp(-dist2 / (2.0 * (self.sigma ** 2)))
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
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

    def _tier_a_feature_names(self) -> List[str]:
        names: List[str] = []
        for pod in CASSANDRA_PODS:
            for base in TIER_A_FEATURES:
                names.append(f"{base}__{pod}")
        return names

    def _query_prom(self, query: str) -> Optional[float]:
        try:
            response = requests.get(
                f"{PROMETHEUS_BASE}/api/v1/query",
                params={"query": query},
                timeout=10,
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
        missing: List[str] = []
        for pod in CASSANDRA_PODS:
            for base_name, template in TIER_A_NODE_QUERY_TEMPLATES.items():
                key = f"{base_name}__{pod}"
                promql = template.replace("__NAMESPACE__", TARGET_NAMESPACE).replace("__POD__", pod)
                value = self._query_prom(promql)
                if value is None or math.isnan(value) or math.isinf(value):
                    missing.append(key)
                else:
                    values[key] = value

        for key, promql in TIER_B_FEATURE_QUERIES.items():
            value = self._query_prom(promql)
            if value is None or math.isnan(value) or math.isinf(value):
                missing.append(key)
            else:
                values[key] = value
        required_missing = [m for m in missing if m in self._tier_a_feature_names()]
        return Sample(
            ts=time.time(),
            values=values,
            quality_valid=len(required_missing) == 0,
            missing=required_missing,
        )

    def _moving_avg(self, history: List[np.ndarray], vec: np.ndarray) -> np.ndarray:
        if SMOOTH_K <= 1:
            return vec
        history.append(vec)
        window = history[-SMOOTH_K:]
        return np.mean(window, axis=0)

    def _normalize_vector(self, values: Dict[str, float]) -> Tuple[np.ndarray, List[str]]:
        missing = [f for f in self.feature_order if f not in values]
        if missing:
            return np.array([]), missing

        raw = np.array([values[f] for f in self.feature_order], dtype=np.float64)
        if not self.norm_max:
            return raw, []

        denom = np.array([max(self.norm_max[f], 1e-9) for f in self.feature_order], dtype=np.float64)
        normed = (raw / denom) * 100.0
        return normed, []

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
        tier_a_features = self._tier_a_feature_names()
        tier_b_candidates = list(TIER_B_FEATURE_QUERIES.keys())
        coverage_threshold = max(1, int(len(valid) * TIER_B_MIN_COVERAGE))
        tier_b_presence = Counter()
        for sample in valid:
            for feature in tier_b_candidates:
                if feature in sample.values:
                    tier_b_presence[feature] += 1
        tier_b_order = [f for f in tier_b_candidates if tier_b_presence[f] >= coverage_threshold]
        self.feature_order = tier_a_features + tier_b_order
        train_rows = []
        for sample in valid:
            if any(feat not in sample.values for feat in self.feature_order):
                continue
            train_rows.append(np.array([sample.values[f] for f in self.feature_order], dtype=np.float64))

        if not train_rows:
            self.last_error = "No complete vectors available for training."
            return

        train_data = np.array(train_rows)
        self.norm_max = {name: float(max(train_data[:, idx].max(), 1e-9)) for idx, name in enumerate(self.feature_order)}
        train_data_norm = (train_data / np.array([self.norm_max[f] for f in self.feature_order])) * 100.0

        self.som = SOM(SOM_ROWS, SOM_COLS, train_data_norm.shape[1], SOM_LR, SOM_SIGMA)
        self.som.train(train_data_norm.copy(), TRAIN_EPOCHS)
        self.area_map = self.som.area_map()
        self.threshold = float(np.percentile(self.area_map.flatten(), THRESHOLD_PERCENTILE))
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
        vec, missing = self._normalize_vector(sample.values)
        if missing:
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

        score_latency = (time.perf_counter() - start) * 1000.0
        self.score_latency_ms.append(score_latency)
        self.total_samples_scored += 1
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
            "missing_required": sample.missing,
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

        return {
            "trained": self.trained,
            "ready": self.ready,
            "phase": self.phase,
            "bootstrap_target_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_collected_samples": len(self.bootstrap_samples),
            "training_duration_sec": round(self.training_duration_sec, 3),
            "total_samples_seen": self.total_samples_seen,
            "total_samples_scored": self.total_samples_scored,
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
        state.score_latency_ms.clear()
        state.bmu_hits.clear()
    return jsonify({"message": "learner reset"})


@app.get("/report")
def report():
    with state.lock:
        return jsonify(_to_builtin(state.report()))


@app.get("/config")
def config():
    tier_a_feature_count = len(TIER_A_FEATURES) * len(CASSANDRA_PODS)
    feature_count_total = tier_a_feature_count + len(TIER_B_FEATURE_QUERIES)
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
            "tier_b_min_coverage": TIER_B_MIN_COVERAGE,
            "tier_a_features": TIER_A_FEATURES,
            "tier_a_feature_count": tier_a_feature_count,
            "tier_b_feature_count": len(TIER_B_FEATURE_QUERIES),
            "feature_count_total": feature_count_total,
        }
    )


def main():
    app.run(host="0.0.0.0", port=8100, threaded=True)


if __name__ == "__main__":
    main()
