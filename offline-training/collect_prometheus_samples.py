#!/usr/bin/env python3
"""
Prometheus Metrics Sample Collector

Collects tier-A metrics from Prometheus over a polling window and writes
raw samples to JSON for offline SOM training.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import main as learner_main
from main import (
    LearnerState,
    PROMETHEUS_BASE as DEFAULT_PROMETHEUS_BASE,
    CASSANDRA_PODS,
    TARGET_NAMESPACE,
    TIER_A_NODE_QUERY_TEMPLATES,
)


def _stop_imported_runtime() -> None:
    """Disable side-effect polling thread started by importing main.py."""
    imported_state = getattr(learner_main, "state", None)
    if imported_state is None:
        return
    if hasattr(imported_state, "running"):
        imported_state.running = False
    imported_thread = getattr(imported_state, "thread", None)
    if imported_thread is not None and imported_thread.is_alive():
        imported_thread.join(timeout=0.2)
    query_pool = getattr(imported_state, "query_pool", None)
    if query_pool is not None:
        query_pool.shutdown(wait=False, cancel_futures=True)


def _build_collection_harness() -> LearnerState:
    """Create a minimal LearnerState object without starting background threads."""
    state = object.__new__(LearnerState)
    state.phase = "offline_collect"
    state.training_samples = []
    state.norm_max = {}
    state.capacity_norm_max_cached = None
    state.capacity_norm_max_cached_at = None
    state.feature_order = []
    state.som = None
    state.area_map = None
    state.threshold = 0.0
    state.trained = False
    state.ready = False
    state.last_error = None
    state.training_duration_sec = 0.0
    state.training_start_ts = None
    state.training_end_ts = None
    return state


def fetch_metrics_samples(
    duration_sec: int,
    poll_interval: float,
    state: LearnerState,
) -> List[Dict[str, object]]:
    """
    Poll Prometheus every poll_interval seconds for duration_sec.
    Collect raw metric samples for each pod and metric.

    Returns:
        List of dicts with keys like "metric__pod" and values as floats.
    """
    samples: List[Dict[str, object]] = []
    start_time = time.time()
    end_time = start_time + duration_sec
    query_jobs = [
        (
            f"{base_name}__{pod}",
            template.replace("__NAMESPACE__", TARGET_NAMESPACE).replace("__POD__", pod),
        )
        for pod in CASSANDRA_PODS
        for base_name, template in TIER_A_NODE_QUERY_TEMPLATES.items()
    ]
    max_workers = max(1, len(query_jobs))

    print(f"[COLLECT] Starting metrics collection for {duration_sec}s (interval: {poll_interval}s)")
    print(f"[COLLECT] Prometheus: {learner_main.PROMETHEUS_BASE}")
    print(f"[COLLECT] Pods: {CASSANDRA_PODS}")

    tick_index = 0
    next_tick = start_time
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            now = time.time()
            if now >= end_time:
                break

            if now < next_tick:
                sleep_time = min(next_tick - now, end_time - now)
                if sleep_time > 0:
                    print(f"[COLLECT] Progress: {now - start_time:.1f}s / {duration_sec}s, sleeping {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                continue

            tick_started_at = time.time()
            sample_dict: Dict[str, float] = {}

            future_to_key = {
                executor.submit(state._query_prom, query): key
                for key, query in query_jobs
            }
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                value = future.result()
                if value is not None:
                    sample_dict[key] = value
                else:
                    print(f"[COLLECT] Missing metric: {key}")

            samples.append(
                {
                    "tick_index": tick_index,
                    "ts": tick_started_at,
                    "values": sample_dict,
                    "metric_count": len(sample_dict),
                }
            )
            print(f"[COLLECT] Sample {len(samples)} @ tick {tick_index}: {len(sample_dict)} metrics collected")

            tick_index += 1
            next_tick = start_time + (tick_index * poll_interval)

    print(f"[COLLECT] Collection complete: {len(samples)} samples")
    return samples


def save_samples(samples: List[Dict[str, object]], output_path: Path) -> Path:
    """Persist collected Prometheus sample dictionaries to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "collected_at_unix": time.time(),
        "sample_count": len(samples),
        "duration_sec": len(samples) and samples[-1].get("ts", 0.0) - samples[0].get("ts", 0.0),
        "samples": samples,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[SAVE] Samples JSON saved to: {output_path}")
    print(f"[SAVE] File size: {output_path.stat().st_size / 1024:.1f} KB")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect Prometheus samples for offline SOM training"
    )
    parser.add_argument(
        "--prometheus-base",
        default=DEFAULT_PROMETHEUS_BASE,
        help=f"Prometheus base URL (default: {DEFAULT_PROMETHEUS_BASE})",
    )
    parser.add_argument(
        "--duration-sec",
        type=int,
        default=180,
        help="Metrics collection duration in seconds (default: 180)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--output-json",
        default="./artifacts/prometheus_samples.json",
        help="Output JSON path for collected samples (default: ./artifacts/prometheus_samples.json)",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("Prometheus Sample Collection")
    print("=" * 80)
    print(f"Prometheus: {args.prometheus_base}")
    print(f"Duration: {args.duration_sec}s, Poll interval: {args.poll_interval}s")
    print(f"Output JSON: {args.output_json}")
    print("=" * 80)

    _stop_imported_runtime()
    learner_main.PROMETHEUS_BASE = args.prometheus_base
    state = _build_collection_harness()
    samples = fetch_metrics_samples(args.duration_sec, args.poll_interval, state)

    if not samples:
        raise RuntimeError("No samples collected; nothing to save")

    save_samples(samples, Path(args.output_json))


if __name__ == "__main__":
    main()
