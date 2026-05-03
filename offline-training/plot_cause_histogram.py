#!/usr/bin/env python3
"""
Histogram of inferred causes from a score_stream.json.

X axis: CPU / Memory / Disk
Y axis: count
Title: "CPU Pressure : Cause Inference"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bucket_for_cause(cause: str) -> str | None:
    # Causes in score_stream are feature base names like:
    # - tier_a_cpu_usage_cores
    # - tier_a_memory_working_set_bytes
    # - tier_a_disk_io_bytes_per_sec
    c = (cause or "").lower()
    if "cpu" in c:
        return "cpu"
    if "memory" in c or "mem" in c:
        return "memory"
    if "disk" in c or "io" in c:
        return "disk"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot histogram of causes (CPU/Memory/Disk) from score_stream.json")
    ap.add_argument(
        "--input",
        type=Path,
        default=Path("../artifacts/scenario-nb-1777232932/score_stream.json"),
        help="Path to score_stream.json",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/cause_histogram.png"),
        help="Output PNG path",
    )
    ap.add_argument(
        "--only-anomalies",
        action="store_true",
        help="Count causes only when diagnosis==abnormal (default: count any non-empty causes)",
    )
    ap.add_argument(
        "--title",
        type=str,
        default="CPU Pressure : Cause Inference",
        help="Plot title",
    )
    args = ap.parse_args()

    obj = _load(args.input)
    items = obj.get("items") if isinstance(obj.get("items"), list) else []

    counts = {"cpu": 0, "memory": 0, "disk": 0}
    for it in items:
        if not isinstance(it, dict):
            continue
        if args.only_anomalies and it.get("diagnosis") != "abnormal":
            continue
        causes = it.get("causes")
        if not isinstance(causes, list):
            continue
        # Causes are ranked; count only the top-1 cause (first position).
        if not causes:
            continue
        cause0 = causes[0]
        if not isinstance(cause0, str):
            continue
        bucket = _bucket_for_cause(cause0)
        if bucket in counts:
            counts[bucket] += 1

    # Lazy import so reading JSON doesn't require matplotlib.
    import matplotlib.pyplot as plt  # type: ignore

    x_labels = ["cpu", "memory", "disk"]
    y_vals = [counts[k] for k in x_labels]

    plt.figure(figsize=(6.5, 4.5), dpi=160)
    plt.bar(["CPU", "Memory", "Disk"], y_vals, color=["#4C78A8", "#F58518", "#54A24B"])
    plt.title(args.title)
    plt.ylabel("count")
    plt.xlabel("cpu, memory, disk")
    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output)
    print(f"[OK] Wrote histogram to {args.output}")


if __name__ == "__main__":
    main()

