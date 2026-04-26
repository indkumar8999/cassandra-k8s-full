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
from flask import Flask, Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Gauge, generate_latest
from sklearn.model_selection import KFold


app = Flask(__name__)

DEMO_EVENT_TOTAL = PromCounter(
    "ubl_demo_event_total",
    "Count of externally published demo events (alarm, scale, rollout).",
    ["event", "source"],
)
DEMO_EVENT_LAST_TS = Gauge(
    "ubl_demo_event_last_timestamp_seconds",
    "Unix epoch timestamp for last published demo event.",
    ["event", "source"],
)
DEMO_EVENT_LAST_RUN = Gauge(
    "ubl_demo_event_last_run_info",
    "Latest published demo event run marker (always 1).",
    ["run_label", "event", "source"],
)
UBL_READY = Gauge("ubl_ready", "Whether learner is ready (1 ready, 0 not ready).")
UBL_TRAINED = Gauge("ubl_trained", "Whether learner is trained (1 trained, 0 not trained).")
UBL_ALARM_COUNT = Gauge("ubl_alarm_count", "Current number of retained learner alarms.")


def _sanitize_label(value: str, default: str = "unknown") -> str:
    raw = (value or "").strip()
    if not raw:
        return default
    cleaned = []
    for ch in raw:
        if ch.isalnum() or ch in ("_", "-", "."):
            cleaned.append(ch)
        else:
            cleaned.append("_")
    return "".join(cleaned)[:80] or default


def _publish_demo_event_metric(event: str, source: str = "learner", run_label: str = "n/a", ts: Optional[float] = None):
    event_lbl = _sanitize_label(event)
    source_lbl = _sanitize_label(source, default="learner")
    run_lbl = _sanitize_label(run_label, default="n_a")
    event_ts = float(ts if ts is not None else time.time())
    DEMO_EVENT_TOTAL.labels(event=event_lbl, source=source_lbl).inc()
    DEMO_EVENT_LAST_TS.labels(event=event_lbl, source=source_lbl).set(event_ts)
    DEMO_EVENT_LAST_RUN.labels(run_label=run_lbl, event=event_lbl, source=source_lbl).set(1.0)


def _sync_runtime_metrics():
    with state.lock:
        UBL_READY.set(1.0 if state.ready else 0.0)
        UBL_TRAINED.set(1.0 if state.trained else 0.0)
        UBL_ALARM_COUNT.set(float(len(state.alarms)))


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
POLL_SEC = _env_float("POLL_SEC", 0.5)
BOOTSTRAP_SAMPLES = _env_int("BOOTSTRAP_SAMPLES", 350)
SOM_ROWS = _env_int("SOM_ROWS", 32)
SOM_COLS = _env_int("SOM_COLS", 32)
SOM_LR = _env_float("SOM_LR", 0.7)
SOM_SIGMA = _env_float("SOM_SIGMA", 4.0)
TRAIN_EPOCHS = _env_int("TRAIN_EPOCHS", 10)
THRESHOLD_PERCENTILE = _env_float("THRESHOLD_PERCENTILE", 85.0)
ANOMALY_STREAK = _env_int("ANOMALY_STREAK", 3)
SMOOTH_K = _env_int("SMOOTH_K", 5)
# Multi-detector comparison knobs (used for /score-stream "models" output).
# Keep SMOOTH_K for backwards compatibility, but do not use it to drive detector behavior.
UBL_NS_TRAIN_SMOOTH_K = _env_int("UBL_NS_TRAIN_SMOOTH_K", 1)
UBL_NS_SCORE_SMOOTH_K = _env_int("UBL_NS_SCORE_SMOOTH_K", 1)
UBL_5PTS_TRAIN_SMOOTH_K = _env_int("UBL_5PTS_TRAIN_SMOOTH_K", 5)
UBL_5PTS_SCORE_SMOOTH_K = _env_int("UBL_5PTS_SCORE_SMOOTH_K", 5)
KNN_K = _env_int("KNN_K", 5)
KNN_REF_SIZE = _env_int("KNN_REF_SIZE", BOOTSTRAP_SAMPLES)
KNN_TAU_PERCENTILE = _env_float("KNN_TAU_PERCENTILE", 95.0)
CAUSE_Q = _env_int("CAUSE_Q", 5)
ONLINE_UPDATE_ENABLED = os.getenv("ONLINE_UPDATE_ENABLED", "1") == "1"
MAX_SCORE_STREAM = _env_int("MAX_SCORE_STREAM", 5000)
MAX_ALARMS = _env_int("MAX_ALARMS", 1000)
TIER_B_MIN_COVERAGE = _env_float("TIER_B_MIN_COVERAGE", 0.9)
TIER_A_MIN_COVERAGE = _env_float("TIER_A_MIN_COVERAGE", 0.67)
TARGET_NAMESPACE = os.getenv("TARGET_NAMESPACE", "cassandra-lab")
CASSANDRA_PODS = [pod.strip() for pod in os.getenv("CASSANDRA_PODS", "cassandra-0,cassandra-1,cassandra-2").split(",") if pod.strip()]
PROM_QUERY_WORKERS = _env_int("PROM_QUERY_WORKERS", 1)
PROM_QUERY_TIMEOUT_SEC = _env_float("PROM_QUERY_TIMEOUT_SEC", 3.0)
THRESHOLD_RECALC_ENABLED = os.getenv("THRESHOLD_RECALC_ENABLED", "1") == "1"
THRESHOLD_RECALC_EVERY_UPDATES = _env_int("THRESHOLD_RECALC_EVERY_UPDATES", 25)
# NoSQLBench SLO enrichment for /score-stream (pull NB p95/p99 from Prometheus).
NB_SLO_THRESHOLD_MS = _env_float("NB_SLO_THRESHOLD_MS", 200.0)
NB_SLO_STEP_SEC = _env_int("NB_SLO_STEP_SEC", 15)
NB_SLO_CACHE_TTL_SEC = _env_float("NB_SLO_CACHE_TTL_SEC", 10.0)
# Path to JSON snapshot (same shape as GET /export/som-snapshot). Reloaded after POST /reset if set.
UBL_SNAPSHOT_PATH = os.getenv("UBL_SNAPSHOT_PATH", "").strip()
DEFAULT_SNAPSHOT_PATH = "/models/som_trained_snapshot.json"


def _effective_snapshot_path() -> str:
    """
    Prefer explicit UBL_SNAPSHOT_PATH. Otherwise auto-detect the baked-in default
    snapshot path if present in the container image.
    """
    if UBL_SNAPSHOT_PATH:
        return UBL_SNAPSHOT_PATH
    return DEFAULT_SNAPSHOT_PATH if os.path.isfile(DEFAULT_SNAPSHOT_PATH) else ""

KNOWN_PHASES = ("normal", "load", "chaos", "cooldown")


TIER_A_NODE_QUERY_TEMPLATES = {
    "tier_a_cpu_usage_cores": 'sum(rate(container_cpu_usage_seconds_total{namespace="__NAMESPACE__",pod="__POD__"}[1m]))',
    "tier_a_memory_working_set_bytes": 'sum(container_memory_working_set_bytes{namespace="__NAMESPACE__",pod="__POD__"})',
    "tier_a_disk_io_bytes_per_sec": (
        'sum(rate(container_fs_reads_bytes_total{namespace="__NAMESPACE__",pod="__POD__"}[1m]))'
        ' + '
        'sum(rate(container_fs_writes_bytes_total{namespace="__NAMESPACE__",pod="__POD__"}[1m]))'
    ),
}



TIER_A_FEATURES = [
    "tier_a_cpu_usage_cores",
    "tier_a_memory_working_set_bytes",
    "tier_a_disk_io_bytes_per_sec",
]

# For averaging, define the base metric names (without pod suffix)
TIER_A_AVG_FEATURES = [
    "tier_a_cpu_usage_cores",
    "tier_a_memory_working_set_bytes",
    "tier_a_disk_io_bytes_per_sec",
]


def _bucket_floor(ts: float, step_sec: int) -> int:
    step = max(1, int(step_sec))
    return int(math.floor(float(ts) / step) * step)


class _NoSQLBenchSLOCache:
    """
    Cache Prometheus query_range results so /score-stream can be enriched without
    issuing many point queries (score-stream can contain thousands of items).
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.fetched_at: float = 0.0
        self.step_sec: int = int(NB_SLO_STEP_SEC)
        self.start_bucket: int = 0
        self.end_bucket: int = 0
        self.p95_by_bucket: Dict[int, float] = {}
        self.p99_by_bucket: Dict[int, float] = {}

    def _query_range(self, promql: str, start_bucket: int, end_bucket: int, step_sec: int) -> Dict[int, float]:
        try:
            resp = requests.get(
                f"{PROMETHEUS_BASE}/api/v1/query_range",
                params={
                    "query": promql,
                    "start": str(int(start_bucket)),
                    "end": str(int(end_bucket)),
                    "step": f"{int(step_sec)}s",
                },
                timeout=max(1.0, float(PROM_QUERY_TIMEOUT_SEC)),
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") != "success":
                return {}
            results = ((payload.get("data") or {}).get("result") or [])
            if not results:
                return {}
            values = results[0].get("values") or []
            out: Dict[int, float] = {}
            for pair in values:
                if not isinstance(pair, list) or len(pair) < 2:
                    continue
                try:
                    ts_i = int(float(pair[0]))
                    val = float(pair[1])
                except (TypeError, ValueError):
                    continue
                out[ts_i] = val
            return out
        except Exception:
            return {}

    def get_for_items(self, items: List[Dict]) -> Tuple[Dict[int, float], Dict[int, float], int]:
        """
        Returns (p95_by_bucket, p99_by_bucket, step_sec) for the time window covered by items.
        Uses TTL-based caching to cap Prometheus query rate.
        """
        if not items:
            return {}, {}, max(1, int(NB_SLO_STEP_SEC))

        step_sec = max(1, int(NB_SLO_STEP_SEC))
        ts_vals: List[float] = []
        for it in items:
            ts = it.get("ts") if isinstance(it, dict) else None
            if ts is None:
                continue
            try:
                ts_vals.append(float(ts))
            except (TypeError, ValueError):
                continue
        if not ts_vals:
            return {}, {}, step_sec

        start_bucket = _bucket_floor(min(ts_vals), step_sec)
        end_bucket = _bucket_floor(max(ts_vals), step_sec)
        now = time.time()

        with self.lock:
            cache_fresh = (now - float(self.fetched_at)) <= float(NB_SLO_CACHE_TTL_SEC)
            cache_covers = (
                bool(self.p95_by_bucket)
                and bool(self.p99_by_bucket)
                and start_bucket >= int(self.start_bucket)
                and end_bucket <= int(self.end_bucket)
            )
            cache_step_ok = int(self.step_sec) == int(step_sec)
            if cache_fresh and cache_covers and cache_step_ok:
                return dict(self.p95_by_bucket), dict(self.p99_by_bucket), step_sec

        # Refresh outside lock (network).
        p95 = self._query_range(
            'max(nosqlbench_histostat_p95_ms{tag="execute"})',
            start_bucket,
            end_bucket,
            step_sec,
        )
        p99 = self._query_range(
            'max(nosqlbench_histostat_p99_ms{tag="execute"})',
            start_bucket,
            end_bucket,
            step_sec,
        )

        with self.lock:
            self.fetched_at = now
            self.step_sec = step_sec
            self.start_bucket = start_bucket
            self.end_bucket = end_bucket
            self.p95_by_bucket = p95
            self.p99_by_bucket = p99

        return dict(p95), dict(p99), step_sec


_NB_SLO_CACHE = _NoSQLBenchSLOCache()


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


class UBLDetector:
    """
    UBL detector instance with per-detector smoothing settings.
    It consumes the shared normalized input vector (0..100 scale) per tick.
    """

    def __init__(self, *, name: str, smooth_k_train: int, smooth_k_score: int):
        self.name = str(name)
        self.smooth_k_train = max(1, int(smooth_k_train))
        self.smooth_k_score = max(1, int(smooth_k_score))

        self.som: Optional[SOM] = None
        self.area_map: Optional[np.ndarray] = None
        self.threshold: float = 0.0
        self.trained: bool = False

        self._score_history: deque[np.ndarray] = deque(maxlen=max(1, self.smooth_k_score))
        self.anomaly_streak: int = 0
        self.bmu_hits = Counter()

        self.training_duration_sec: float = 0.0
        self.training_start_ts: Optional[float] = None
        self.training_end_ts: Optional[float] = None
        self.kfold_metrics: Optional[List[Dict]] = None

    def _moving_avg(self, vec: np.ndarray) -> np.ndarray:
        if self.smooth_k_score <= 1:
            return vec
        self._score_history.append(vec)
        window = list(self._score_history)
        return np.mean(window, axis=0)

    def _apply_training_smoothing(self, data: np.ndarray) -> np.ndarray:
        k = self.smooth_k_train
        if k <= 1 or len(data) <= 1:
            return data
        smoothed = []
        for idx in range(len(data)):
            lo = max(0, idx - k + 1)
            smoothed.append(np.mean(data[lo : idx + 1], axis=0))
        return np.array(smoothed, dtype=np.float64)

    def _refresh_threshold(self):
        if self.area_map is None:
            return
        self.threshold = float(np.percentile(self.area_map.flatten(), THRESHOLD_PERCENTILE))

    def train(self, train_data_norm: np.ndarray):
        """
        Train UBL (SOM) on shared normalized data (0..100 scale).
        Uses 3-fold CV to select best SOM among 3 initializations (by min validation BMU area sum).
        """
        if train_data_norm is None or len(train_data_norm) == 0:
            return

        self.training_start_ts = time.time()
        X = self._apply_training_smoothing(np.asarray(train_data_norm, dtype=np.float64))

        k = 3
        kf = KFold(n_splits=k, shuffle=True, random_state=42)
        fold_metrics: List[Dict] = []
        som_models: List[Dict] = []

        for fold, (train_idx, test_idx) in enumerate(kf.split(X)):
            X_train, X_val = X[train_idx], X[test_idx]
            som = SOM(SOM_ROWS, SOM_COLS, X_train.shape[1], SOM_LR, SOM_SIGMA, radius=2)
            som.train(X_train.copy(), TRAIN_EPOCHS)
            area_map = som.area_map()

            val_areas = []
            for vec in X_val:
                bmu_r, bmu_c = som.bmu(vec)
                val_areas.append(area_map[bmu_r, bmu_c])
            sum_area = float(np.sum(val_areas)) if val_areas else float("inf")
            fold_metrics.append(
                {
                    "model": self.name,
                    "fold": fold + 1,
                    "sum_area": sum_area,
                    "mean_area": float(np.mean(val_areas)) if val_areas else 0.0,
                    "std_area": float(np.std(val_areas)) if val_areas else 0.0,
                    "min_area": float(np.min(val_areas)) if val_areas else 0.0,
                    "max_area": float(np.max(val_areas)) if val_areas else 0.0,
                }
            )
            som_models.append({"model": som, "area_map": area_map, "sum_area": sum_area})

        best_idx = int(np.argmin([m["sum_area"] for m in som_models]))
        best_som = som_models[best_idx]["model"]
        best_area_map = som_models[best_idx]["area_map"]

        self.som = best_som
        self.area_map = best_area_map
        self._refresh_threshold()
        self.trained = True
        self.kfold_metrics = fold_metrics
        self.training_end_ts = time.time()
        self.training_duration_sec = float(self.training_end_ts - float(self.training_start_ts or self.training_end_ts))

    def score(self, vec_norm: np.ndarray, *, phase: str, online_update: bool) -> Dict:
        if self.som is None or self.area_map is None:
            return {"ready": False}

        start = time.perf_counter()
        vec = self._moving_avg(np.asarray(vec_norm, dtype=np.float64))
        bmu_r, bmu_c = self.som.bmu(vec)
        area_value = float(self.area_map[bmu_r, bmu_c])
        is_anomaly = area_value >= float(self.threshold)
        self.anomaly_streak = self.anomaly_streak + 1 if is_anomaly else 0
        self.bmu_hits[f"{bmu_r},{bmu_c}"] += 1

        causes: List[str] = []
        if is_anomaly and CAUSE_Q > 0:
            # Cause ranking uses SOM weight diffs vs nearest "normal" neighbors in area-map space.
            max_radius = max(self.som.rows, self.som.cols)
            normal_neighbors: List[Tuple[int, int]] = []
            for radius in range(1, max_radius + 1):
                for r in range(max(0, bmu_r - radius), min(self.som.rows, bmu_r + radius + 1)):
                    for c in range(max(0, bmu_c - radius), min(self.som.cols, bmu_c + radius + 1)):
                        if abs(r - bmu_r) + abs(c - bmu_c) > radius:
                            continue
                        if float(self.area_map[r, c]) < float(self.threshold):
                            normal_neighbors.append((r, c))
                        if len(normal_neighbors) >= CAUSE_Q:
                            break
                    if len(normal_neighbors) >= CAUSE_Q:
                        break
                if len(normal_neighbors) >= CAUSE_Q:
                    break
            if normal_neighbors:
                anomaly_vec = self.som.weights[bmu_r, bmu_c]
                votes = Counter()
                for nr, nc in normal_neighbors:
                    diffs = np.abs(anomaly_vec - self.som.weights[nr, nc])
                    top_idx = int(np.argmax(diffs))
                    votes[TIER_A_AVG_FEATURES[top_idx]] += 1
                causes = [name for name, _ in votes.most_common()]

        # Optional online update (same as original: skip during chaos).
        if online_update and phase != "chaos":
            self.som.train_step(vec)
            self.area_map = self.som.area_map()

        score_latency = (time.perf_counter() - start) * 1000.0
        return {
            "ready": True,
            "score_area": area_value,
            "threshold": float(self.threshold),
            "is_anomaly": bool(is_anomaly),
            "streak": int(self.anomaly_streak),
            "bmu": [int(bmu_r), int(bmu_c)],
            "causes": causes,
            "score_latency_ms": round(float(score_latency), 3),
        }


class KNNDetector:
    """
    Unsupervised k-NN distance scoring.
    "Training" here means freezing a reference set X_ref; thresholding is done offline.
    """

    def __init__(self, *, k: int, ref_size: int, tau_percentile: float):
        self.k = max(1, int(k))
        self.ref_size = max(1, int(ref_size))
        self.tau_percentile = float(tau_percentile)
        self._ref: List[np.ndarray] = []
        self.ready: bool = False
        self.tau: Optional[float] = None

    def _fit_tau_from_reference(self):
        if not self._ref:
            self.tau = None
            return
        X = np.vstack(self._ref)
        n = int(X.shape[0])
        if n <= 1:
            self.tau = None
            return

        k_excl = min(self.k + 1, n)
        baseline_scores = np.zeros((n,), dtype=np.float64)
        for i in range(n):
            d = np.linalg.norm(X - X[i], axis=1)
            baseline_scores[i] = float(np.partition(d, k_excl - 1)[k_excl - 1])

        pct = float(min(max(self.tau_percentile, 0.0), 100.0))
        self.tau = float(np.percentile(baseline_scores, pct))

    def consider_for_reference(self, vec_norm: np.ndarray):
        if self.ready:
            return
        self._ref.append(np.asarray(vec_norm, dtype=np.float64))
        if len(self._ref) >= self.ref_size:
            self.ready = True
            self._fit_tau_from_reference()

    def score(self, vec_norm: np.ndarray) -> Dict:
        if not self.ready or not self._ref:
            return {"ready": False}

        X = np.vstack(self._ref)  # (N, d)
        x = np.asarray(vec_norm, dtype=np.float64).reshape(1, -1)  # (1, d)
        dists = np.linalg.norm(X - x, axis=1)
        kth = min(self.k, max(1, len(dists)))
        # kth nearest (1-indexed) => index kth-1
        score = float(np.partition(dists, kth - 1)[kth - 1])
        is_anomaly = bool(self.tau is not None and score >= float(self.tau))
        return {
            "ready": True,
            "score_knn_kth": score,
            "k": int(self.k),
            "ref_size": int(len(self._ref)),
            "tau": float(self.tau) if self.tau is not None else None,
            "tau_percentile": float(self.tau_percentile),
            "is_anomaly": is_anomaly,
        }


class LearnerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "normal"
        self.ready = False
        self.trained = False
        self.bootstrap_samples: List[Sample] = []
        # Shared normalization (applies to all detectors): raw feature maxima (capacity or observed).
        self.norm_max: Dict[str, float] = {}
        self.capacity_norm_max_cached: Optional[Dict[str, float]] = None
        self.capacity_norm_max_cached_at: Optional[float] = None
        self.feature_order: List[str] = []
        # Backwards-compatible primary model fields (kept for /alarms and legacy dashboards).
        self.som: Optional[SOM] = None
        self.area_map: Optional[np.ndarray] = None
        self.threshold: float = 0.0
        self.anomaly_streak = 0

        # Multi-model detectors for comparison.
        self.ubl_ns = UBLDetector(name="ubl_ns", smooth_k_train=UBL_NS_TRAIN_SMOOTH_K, smooth_k_score=UBL_NS_SCORE_SMOOTH_K)
        self.ubl_5pts = UBLDetector(
            name="ubl_5pts", smooth_k_train=UBL_5PTS_TRAIN_SMOOTH_K, smooth_k_score=UBL_5PTS_SCORE_SMOOTH_K
        )
        self.knn = KNNDetector(k=KNN_K, ref_size=KNN_REF_SIZE, tau_percentile=KNN_TAU_PERCENTILE)

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
        self.dropped_missing_tier_b = 0
        self.last_missing_required: List[str] = []
        self.last_tier_a_coverage: Dict[str, float] = {}
        self.online_updates_since_threshold_refresh = 0
        self.query_pool = ThreadPoolExecutor(max_workers=max(1, PROM_QUERY_WORKERS))
        self.running = True
        self.snapshot_loaded_from: Optional[str] = None
        snapshot_path = _effective_snapshot_path()
        if snapshot_path:
            if os.path.isfile(snapshot_path):
                if self._apply_som_snapshot_unlocked(snapshot_path):
                    self.snapshot_loaded_from = snapshot_path
            else:
                self.last_error = f"Snapshot path configured but file missing: {snapshot_path}"
                print(f"[SNAPSHOT] {self.last_error}")
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

    def _apply_som_snapshot_unlocked(self, path: str) -> bool:
        """
        Load a pretrained SOM from disk (offline export / train_offline_wout_no_of_samples.py).
        Caller must not run this concurrently with _poll_loop unless self.lock is held.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as ex:
            self.last_error = f"snapshot read failed ({path}): {ex}"
            print(f"[SNAPSHOT] {self.last_error}")
            return False

        required_keys = ("som_rows", "som_cols", "feature_order", "norm_max", "threshold", "weights", "area_map")
        for key in required_keys:
            if key not in data:
                self.last_error = f"snapshot missing key {key!r}"
                print(f"[SNAPSHOT] {self.last_error}")
                return False

        feature_order = list(data["feature_order"])
        if feature_order != TIER_A_AVG_FEATURES:
            self.last_error = (
                f"snapshot feature_order mismatch: expected {TIER_A_AVG_FEATURES}, got {feature_order}"
            )
            print(f"[SNAPSHOT] {self.last_error}")
            return False

        rows = int(data["som_rows"])
        cols = int(data["som_cols"])
        dims = len(feature_order)
        weights = np.asarray(data["weights"], dtype=np.float64)
        if weights.shape != (rows, cols, dims):
            self.last_error = f"snapshot weights shape {weights.shape}, expected {(rows, cols, dims)}"
            print(f"[SNAPSHOT] {self.last_error}")
            return False

        area_map = np.asarray(data["area_map"], dtype=np.float64)
        if area_map.shape != (rows, cols):
            self.last_error = f"snapshot area_map shape {area_map.shape}, expected {(rows, cols)}"
            print(f"[SNAPSHOT] {self.last_error}")
            return False

        raw_norm = data["norm_max"]
        if not isinstance(raw_norm, dict):
            self.last_error = "snapshot norm_max must be an object"
            print(f"[SNAPSHOT] {self.last_error}")
            return False
        norm_max: Dict[str, float] = {str(k): float(v) for k, v in raw_norm.items()}
        for name in feature_order:
            if name not in norm_max:
                self.last_error = f"snapshot norm_max missing key {name!r}"
                print(f"[SNAPSHOT] {self.last_error}")
                return False

        som = SOM(rows, cols, dims, SOM_LR, SOM_SIGMA, radius=2)
        som.weights = weights
        self.som = som
        self.area_map = area_map
        self.feature_order = list(feature_order)
        self.norm_max = {k: float(norm_max[k]) for k in feature_order}
        self.threshold = float(data["threshold"])
        if hasattr(self, "kfold_metrics"):
            delattr(self, "kfold_metrics")
        self.bootstrap_samples.clear()
        self.trained = True
        self.ready = True
        self.last_error = None
        print(
            f"[SNAPSHOT] Loaded SOM from {path} rows={rows} cols={cols} dims={dims} "
            f"threshold={self.threshold}"
        )
        return True

    def _query_prom_scalar_best_effort(self, queries: List[str]) -> Optional[float]:
        for q in queries:
            value = self._query_prom(q)
            if value is not None and not math.isnan(value) and not math.isinf(value):
                return float(value)
        return None

    def _capacity_norm_max(self) -> Dict[str, float]:
        if self.capacity_norm_max_cached is not None:
            return dict(self.capacity_norm_max_cached)

        ns = TARGET_NAMESPACE
        pod_re = "cassandra-[0-9]+"
        pvc_re = "cassandra-data-cassandra-[0-9]+"

        cpu_queries = [
            # kube-state-metrics (preferred)
            (
                f'max(sum by (pod) (kube_pod_container_resource_limits{{namespace="{ns}",pod=~"{pod_re}",resource="cpu",unit="core"}}))'
            ),
            # older kube-state-metrics variants without unit label
            (
                f'max(sum by (pod) (kube_pod_container_resource_limits{{namespace="{ns}",pod=~"{pod_re}",resource="cpu"}}))'
            ),
        ]
        mem_queries = [
            (
                f'max(sum by (pod) (kube_pod_container_resource_limits{{namespace="{ns}",pod=~"{pod_re}",resource="memory",unit="byte"}}))'
            ),
            (
                f'max(sum by (pod) (kube_pod_container_resource_limits{{namespace="{ns}",pod=~"{pod_re}",resource="memory"}}))'
            ),
        ]
        disk_queries = [
            # kubelet volume stats (capacity bytes) if available
            f'max(max by (persistentvolumeclaim) (kubelet_volume_stats_capacity_bytes{{namespace="{ns}",persistentvolumeclaim=~"{pvc_re}"}}))',
            # kube-state-metrics PVC request bytes fallback
            f'max(max by (persistentvolumeclaim) (kube_persistentvolumeclaim_resource_requests_storage_bytes{{namespace="{ns}",persistentvolumeclaim=~"{pvc_re}"}}))',
        ]

        cpu_limit_cores = self._query_prom_scalar_best_effort(cpu_queries)
        mem_limit_bytes = self._query_prom_scalar_best_effort(mem_queries)
        pvc_bytes = self._query_prom_scalar_best_effort(disk_queries)/1e3 # convert to MB

        result: Dict[str, float] = {}
        if cpu_limit_cores is not None:
            result["tier_a_cpu_usage_cores"] = float(max(cpu_limit_cores, 1e-9))
        if mem_limit_bytes is not None:
            result["tier_a_memory_working_set_bytes"] = float(max(mem_limit_bytes, 1e-9))
        if pvc_bytes is not None:
            # NOTE: Unit mismatch with tier_a_disk_io_bytes_per_sec; kept as requested (capacity-based normalization).
            result["tier_a_disk_io_bytes_per_sec"] = float(max(pvc_bytes, 1e-9))

        self.capacity_norm_max_cached = dict(result)
        self.capacity_norm_max_cached_at = time.time()
        if not result:
            print(
                f"PHASE:{self.phase} Capacity norm unavailable; falling back to observed maxima. "
                f"Check kube-state-metrics / kubelet volume metrics in Prometheus."
            )
        else:
            print(f"PHASE:{self.phase} Capacity norm maxima cached: {result}")
        return dict(result)

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
        print(f"[SAMPLE VALUES] PHASE:{self.phase} Averaging features for sample : {sample.values}:")
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
                print(f"PHASE:{self.phase} Prometheus query failed : {payload}")
                return None
            result = payload.get("data", {}).get("result", [])
            if not result:
                print(f"PHASE:{self.phase} Prometheus query returned no data: {query}")
                return None
            print(f"PHASE:{self.phase} Prometheus query result for '{query}': {result}")  
            return float(result[0]["value"][1])
        except Exception:
            print(f"PHASE:{self.phase} Error querying Prometheus for '{query}': ")
            return None

    def _collect_sample(self) -> Sample:
        values: Dict[str, float] = {}
        required_missing: List[str] = []
        tier_a_coverage: Dict[str, float] = {}

        query_jobs = []
        for pod in CASSANDRA_PODS:
            for base_name, template in TIER_A_NODE_QUERY_TEMPLATES.items():
                key = f"{base_name}__{pod}"
                promql = template.replace("__NAMESPACE__", TARGET_NAMESPACE).replace("__POD__", pod)
                query_jobs.append((key, promql))

        future_to_meta = {
            self.query_pool.submit(self._query_prom, promql): key for key, promql in query_jobs
        }
        for future in as_completed(future_to_meta):
            key = future_to_meta[future]
            value = future.result()
            if value is None or math.isnan(value) or math.isinf(value):
                continue
            values[key] = value

        # Coverage-based validity: allow sampling during pod moves as long as enough pods report metrics.
        total_pods = max(1, len(CASSANDRA_PODS))
        for base_name in TIER_A_NODE_QUERY_TEMPLATES.keys():
            have = sum(1 for pod in CASSANDRA_PODS if f"{base_name}__{pod}" in values)
            coverage = have / float(total_pods)
            tier_a_coverage[base_name] = coverage
            if coverage < TIER_A_MIN_COVERAGE:
                for pod in CASSANDRA_PODS:
                    key = f"{base_name}__{pod}"
                    if key not in values:
                        required_missing.append(key)

        self.last_missing_required = list(required_missing)
        self.last_tier_a_coverage = dict(tier_a_coverage)

        return Sample(
            ts=time.time(),
            values=values,
            quality_valid=len(required_missing) == 0,
            missing_required=required_missing,
            missing_tier_b=[],
        )

    def _vectorize_raw(self, sample: Sample) -> Tuple[np.ndarray, List[str]]:
        """
        Shared feature extraction: average tier-A metrics across pods, in raw units.
        Returns (raw_vec, missing_required).
        """
        avg_features = self._avg_tier_a_features(sample)
        raw_values = [avg_features[feature] for feature in TIER_A_AVG_FEATURES]
        raw = np.array(raw_values, dtype=np.float64)
        return raw, []

    def _normalize_raw_vector(self, raw_vec: np.ndarray) -> np.ndarray:
        """
        Shared normalization used for *all* detectors.
        If norm_max isn't ready yet, return raw vector (still numeric) so bootstrap can proceed.
        """
        raw = np.asarray(raw_vec, dtype=np.float64)
        if not self.norm_max:
            return raw
        denom = np.array([max(float(self.norm_max[f]), 1e-9) for f in TIER_A_AVG_FEATURES], dtype=np.float64)
        return (raw / denom) * 100.0

    def _refresh_threshold(self):
        if self.area_map is None:
            return
        self.threshold = float(np.percentile(self.area_map.flatten(), THRESHOLD_PERCENTILE))

    def _train(self):
        valid = [s for s in self.bootstrap_samples if s.quality_valid]
        if len(valid) < BOOTSTRAP_SAMPLES:
            return

        self.training_start_ts = time.time()
        self.feature_order = TIER_A_AVG_FEATURES.copy()
        train_rows_raw: List[np.ndarray] = []
        for sample in valid:
            raw_vec, _missing = self._vectorize_raw(sample)
            train_rows_raw.append(raw_vec)

        if not train_rows_raw:
            self.last_error = "No complete vectors available for training."
            return

        train_raw = np.array(train_rows_raw, dtype=np.float64)
        observed_max = {name: float(max(train_raw[:, idx].max(), 1e-9)) for idx, name in enumerate(self.feature_order)}
        capacity_max = self._capacity_norm_max()
        self.norm_max = {
            name: float(max(capacity_max.get(name, observed_max.get(name, 1e-9)), 1e-9))
            for name in self.feature_order
        }

        # Normalize raw vectors once (shared across detectors and knn reference set).
        denom = np.array([self.norm_max[f] for f in self.feature_order], dtype=np.float64)
        train_norm = (train_raw / denom) * 100.0

        # Train both UBL detectors from the same normalized input sequence.
        self.ubl_ns.train(train_norm)
        self.ubl_5pts.train(train_norm)

        # Backwards-compatible primary model points to UBL-5PtS.
        self.som = self.ubl_5pts.som
        self.area_map = self.ubl_5pts.area_map
        self.threshold = float(self.ubl_5pts.threshold)

        # Record training stats (use primary for legacy fields).
        self.kfold_metrics = self.ubl_5pts.kfold_metrics or []
        self.trained = bool(self.ubl_5pts.trained and self.ubl_ns.trained)
        self.ready = self.trained
        self.training_end_ts = time.time()
        self.training_duration_sec = float(self.training_end_ts - float(self.training_start_ts or self.training_end_ts))

    def _record_alarm(self, payload: Dict):
        self.alarms.append(payload)
        _publish_demo_event_metric("alarm_detected", source="ubl-learner", run_label="learner", ts=payload.get("ts"))

    def _poll_loop(self):
        while self.running:
            with self.lock:
                try:
                    sample = self._collect_sample()
                    self.total_samples_seen += 1
                    if not self.trained:
                        self.bootstrap_samples.append(sample)
                        self._train()
                    if not sample.quality_valid:
                        self.dropped_missing_tier_a += 1
                        continue

                    raw_vec, _missing = self._vectorize_raw(sample)
                    vec_norm = self._normalize_raw_vector(raw_vec)

                    # Always feed KNN reference set during bootstrap period; it freezes when ref_size is reached.
                    self.knn.consider_for_reference(vec_norm)

                    # Score all detectors on the same vector.
                    ubl_ns_out = self.ubl_ns.score(vec_norm, phase=self.phase, online_update=ONLINE_UPDATE_ENABLED)
                    ubl_5pts_out = self.ubl_5pts.score(vec_norm, phase=self.phase, online_update=ONLINE_UPDATE_ENABLED)
                    knn_out = self.knn.score(vec_norm)

                    # Backwards-compatible primary model mirrors UBL-5PtS.
                    primary_ready = bool(ubl_5pts_out.get("ready"))
                    if primary_ready:
                        self.threshold = float(ubl_5pts_out.get("threshold", self.threshold))
                        self.anomaly_streak = int(ubl_5pts_out.get("streak", 0))

                    # Latency accounting: use primary model timing for continuity.
                    if "score_latency_ms" in ubl_5pts_out:
                        self.score_latency_ms.append(float(ubl_5pts_out["score_latency_ms"]))
                    self.total_samples_scored += 1
                    self.scored_by_phase[self.phase] += 1

                    event = {
                        "ts": sample.ts,
                        "phase": self.phase,
                        "input_vector": np.asarray(vec_norm, dtype=np.float64).tolist(),
                        "quality_valid": sample.quality_valid,
                        "missing_required": sample.missing_required,
                        "missing_tier_b": sample.missing_tier_b,
                        "models": {
                            "ubl_ns": _to_builtin(ubl_ns_out),
                            "ubl_5pts": _to_builtin(ubl_5pts_out),
                            "knn": _to_builtin(knn_out),
                        },
                    }

                    # Legacy top-level fields (primary = UBL-5PtS).
                    if primary_ready:
                        event["score_area"] = float(ubl_5pts_out.get("score_area", 0.0))
                        event["threshold"] = float(ubl_5pts_out.get("threshold", 0.0))
                        event["diagnosis"] = "abnormal" if bool(ubl_5pts_out.get("is_anomaly")) else "normal"
                        event["streak"] = int(ubl_5pts_out.get("streak", 0))
                        event["bmu"] = ubl_5pts_out.get("bmu")
                        event["causes"] = ubl_5pts_out.get("causes", [])
                        event["score_latency_ms"] = ubl_5pts_out.get("score_latency_ms")

                        # Preserve alarm behavior for primary model.
                        if int(ubl_5pts_out.get("streak", 0)) >= int(ANOMALY_STREAK):
                            self._record_alarm(
                                {
                                    "ts": sample.ts,
                                    "phase": self.phase,
                                    "score_area": float(ubl_5pts_out.get("score_area", 0.0)),
                                    "threshold": float(ubl_5pts_out.get("threshold", 0.0)),
                                    "bmu": ubl_5pts_out.get("bmu"),
                                    "causes": ubl_5pts_out.get("causes", []),
                                    "streak": int(ubl_5pts_out.get("streak", 0)),
                                }
                            )

                    self.score_stream.append(event)
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
            "multi_models": {
                "ubl_ns": {
                    "trained": self.ubl_ns.trained,
                    "smooth_k_train": self.ubl_ns.smooth_k_train,
                    "smooth_k_score": self.ubl_ns.smooth_k_score,
                    "threshold": self.ubl_ns.threshold,
                },
                "ubl_5pts": {
                    "trained": self.ubl_5pts.trained,
                    "smooth_k_train": self.ubl_5pts.smooth_k_train,
                    "smooth_k_score": self.ubl_5pts.smooth_k_score,
                    "threshold": self.ubl_5pts.threshold,
                },
                "knn": {
                    "ready": self.knn.ready,
                    "k": self.knn.k,
                    "ref_size": self.knn.ref_size,
                    "tau_percentile": self.knn.tau_percentile,
                    "tau": self.knn.tau,
                },
            },
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
                "snapshot_loaded_from": state.snapshot_loaded_from,
                "bootstrap_collected_samples": len(state.bootstrap_samples),
                "bootstrap_valid_samples": valid_bootstrap_samples,
                "bootstrap_target_samples": BOOTSTRAP_SAMPLES,
                "training_duration_sec": round(state.training_duration_sec, 3),
                "threshold": state.threshold,
                "threshold_percentile": THRESHOLD_PERCENTILE,
                "tier_a_min_coverage": TIER_A_MIN_COVERAGE,
                "last_tier_a_coverage": state.last_tier_a_coverage,
                "last_missing_required_count": len(state.last_missing_required),
                "last_missing_required": state.last_missing_required[:50],
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
    items = _to_builtin(data)

    # Enrich with NoSQLBench p95/p99 and SLO violation flag.
    # Note: do not hold the learner state lock while querying Prometheus.
    p95_by_bucket: Dict[int, float] = {}
    p99_by_bucket: Dict[int, float] = {}
    step_sec = max(1, int(NB_SLO_STEP_SEC))
    try:
        dict_items = [it for it in items if isinstance(it, dict)]
        p95_by_bucket, p99_by_bucket, step_sec = _NB_SLO_CACHE.get_for_items(dict_items)
    except Exception:
        p95_by_bucket, p99_by_bucket = {}, {}

    for item in items:
        if not isinstance(item, dict):
            continue
        is_anomaly = item.pop("is_anomaly", None)
        if is_anomaly is True:
            item["diagnosis"] = "abnormal"
        elif is_anomaly is False:
            item["diagnosis"] = "normal"
        else:
            # Backfill for older/partial items without anomaly flag
            item.setdefault("diagnosis", "unknown")

        # Align NB stats to the closest step bucket at/before item ts.
        ts = item.get("ts")
        p95_ms = None
        p99_ms = None
        try:
            if ts is not None:
                bucket = _bucket_floor(float(ts), step_sec)
                p95_ms = p95_by_bucket.get(bucket)
                p99_ms = p99_by_bucket.get(bucket)
        except (TypeError, ValueError):
            p95_ms = None
            p99_ms = None

        item["p95_ms"] = p95_ms
        item["p99_ms"] = p99_ms
        item["slo_violated"] = bool(p95_ms is not None and float(p95_ms) > float(NB_SLO_THRESHOLD_MS))
    return jsonify({"count": len(items), "items": items})


@app.get("/alarms")
def alarms():
    limit = int(request.args.get("limit", "200"))
    with state.lock:
        data = list(state.alarms)[-limit:]
    return jsonify({"count": len(data), "items": _to_builtin(data)})


@app.post("/demo-event")
def demo_event():
    body = request.get_json(silent=True) or {}
    event = _sanitize_label(str(body.get("event", "")), default="")
    if not event:
        return jsonify({"error": "event is required"}), 400
    source = _sanitize_label(str(body.get("source", "automation")), default="automation")
    run_label = _sanitize_label(str(body.get("run_label", "manual")), default="manual")

    ts_val = body.get("ts")
    ts = None
    if ts_val is not None:
        try:
            ts = float(ts_val)
        except (TypeError, ValueError):
            return jsonify({"error": "ts must be numeric if provided"}), 400

    _publish_demo_event_metric(event=event, source=source, run_label=run_label, ts=ts)
    return jsonify({"message": "event recorded", "event": event, "source": source, "run_label": run_label})


@app.get("/metrics")
def metrics():
    _sync_runtime_metrics()
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


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
        state.dropped_missing_tier_b = 0
        state.last_missing_required = []
        state.last_tier_a_coverage = {}
        state.score_latency_ms.clear()
        state.bmu_hits.clear()
        state.scored_by_phase.clear()
        state.online_updates_since_threshold_refresh = 0
        # Reset comparison detectors.
        state.ubl_ns = UBLDetector(name="ubl_ns", smooth_k_train=UBL_NS_TRAIN_SMOOTH_K, smooth_k_score=UBL_NS_SCORE_SMOOTH_K)
        state.ubl_5pts = UBLDetector(
            name="ubl_5pts", smooth_k_train=UBL_5PTS_TRAIN_SMOOTH_K, smooth_k_score=UBL_5PTS_SCORE_SMOOTH_K
        )
        state.knn = KNNDetector(k=KNN_K, ref_size=KNN_REF_SIZE, tau_percentile=KNN_TAU_PERCENTILE)
        state.snapshot_loaded_from = None
        snapshot_path = _effective_snapshot_path()
        if snapshot_path:
            if os.path.isfile(snapshot_path):
                if state._apply_som_snapshot_unlocked(snapshot_path):
                    state.snapshot_loaded_from = snapshot_path
            else:
                state.last_error = f"Snapshot path configured but file missing: {snapshot_path}"
    return jsonify({"message": "learner reset"})


@app.get("/report")
def report():
    with state.lock:
        return jsonify(_to_builtin(state.report()))


@app.get("/export/som-snapshot")
def export_som_snapshot():
    """Read-only export of trained SOM weights and area map for offline artifacts / plots."""
    with state.lock:
        if state.som is None or state.area_map is None:
            return jsonify({"error": "SOM not trained", "trained": state.trained}), 503
        som = state.som
        area_np = state.area_map
        feature_order = list(state.feature_order)
        norm_max = dict(state.norm_max)
        threshold = float(state.threshold)
        kfold_metrics = getattr(state, "kfold_metrics", None)
    # Avoid holding state.lock during large .tolist() / JSON encode (reduces stalls and flaky clients).
    payload = {
        "som_rows": som.rows,
        "som_cols": som.cols,
        "feature_order": feature_order,
        "norm_max": norm_max,
        "threshold": threshold,
        "threshold_percentile": float(THRESHOLD_PERCENTILE),
        "weights": som.weights.tolist(),
        "area_map": area_np.tolist(),
    }
    if kfold_metrics is not None:
        payload["kfold_metrics"] = kfold_metrics
    body = json.dumps(_to_builtin(payload))
    return Response(body, mimetype="application/json")


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
            "ubl_ns_train_smooth_k": UBL_NS_TRAIN_SMOOTH_K,
            "ubl_ns_score_smooth_k": UBL_NS_SCORE_SMOOTH_K,
            "ubl_5pts_train_smooth_k": UBL_5PTS_TRAIN_SMOOTH_K,
            "ubl_5pts_score_smooth_k": UBL_5PTS_SCORE_SMOOTH_K,
            "knn_k": KNN_K,
            "knn_ref_size": KNN_REF_SIZE,
            "knn_tau_percentile": float(KNN_TAU_PERCENTILE),
            "cause_q": CAUSE_Q,
            "online_update_enabled": ONLINE_UPDATE_ENABLED,
            "threshold_recalc_enabled": THRESHOLD_RECALC_ENABLED,
            "threshold_recalc_every_updates": THRESHOLD_RECALC_EVERY_UPDATES,
            "prom_query_workers": PROM_QUERY_WORKERS,
            "prom_query_timeout_sec": PROM_QUERY_TIMEOUT_SEC,
            "tier_a_features": TIER_A_FEATURES,
            "tier_a_feature_count": tier_a_feature_count,
            "ubl_snapshot_path": _effective_snapshot_path() or None,
        }
    )


def main():
    app.run(host="0.0.0.0", port=8100, threaded=True)


if __name__ == "__main__":
    main()
