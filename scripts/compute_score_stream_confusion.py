#!/usr/bin/env python3
"""Compute FP/FN/TP/TN for a tagged score_stream.json file.

Rules implemented from user requirements:
- Ground truth anomaly: slo_violated == True
- Predicted alarm: diagnosis == "abnormal"
- Rolling window: default 10 seconds
- Alarm row classification:
  - TP if there is a future breach timestamp b where ts in [b - window, b)
  - FP otherwise
- Non-alarm row classification:
  - FN if row is a breach and there is no prior alarm in [ts - window, ts)
  - TN otherwise

Counts are sample-level (each row contributes exactly one of FP/FN/TP/TN).
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
from pathlib import Path
from typing import Dict, List


def load_items(input_path: Path) -> List[dict]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if not isinstance(items, list):
        raise ValueError("Expected 'items' to be a list in input JSON")
    return items


def compute_counts(items: List[dict], window_seconds: float) -> Dict[str, int]:
    breach_ts = sorted(
        float(item["ts"])
        for item in items
        if item.get("slo_violated") is True and item.get("ts") is not None
    )
    alarm_ts = sorted(
        float(item["ts"])
        for item in items
        if item.get("diagnosis") == "abnormal" and item.get("ts") is not None
    )

    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

    for item in items:
        if item.get("ts") is None:
            continue

        ts = float(item["ts"])
        is_alarm = item.get("diagnosis") == "abnormal"
        is_breach = item.get("slo_violated") is True

        if is_alarm:
            next_breach_idx = bisect.bisect_right(breach_ts, ts)
            has_future_breach_in_window = (
                next_breach_idx < len(breach_ts)
                and breach_ts[next_breach_idx] <= ts + window_seconds
            )
            if has_future_breach_in_window:
                counts["tp"] += 1
            else:
                counts["fp"] += 1
            continue

        if is_breach:
            window_start = ts - window_seconds
            first_alarm_idx = bisect.bisect_left(alarm_ts, window_start)
            has_prior_alarm_in_window = (
                first_alarm_idx < len(alarm_ts) and alarm_ts[first_alarm_idx] < ts
            )
            if has_prior_alarm_in_window:
                counts["tn"] += 1
            else:
                counts["fn"] += 1
            continue

        counts["tn"] += 1

    return counts


def write_reports(
    input_path: Path,
    output_json_path: Path,
    output_csv_path: Path,
    window_seconds: float,
    counts: Dict[str, int],
    total_rows: int,
) -> None:
    report = {
        "input_file": str(input_path),
        "window_seconds": window_seconds,
        "total_rows": total_rows,
        "counts": counts,
    }
    output_json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    with output_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "count"])
        writer.writerow(["tp", counts["tp"]])
        writer.writerow(["fp", counts["fp"]])
        writer.writerow(["fn", counts["fn"]])
        writer.writerow(["tn", counts["tn"]])
        writer.writerow(["total_rows", total_rows])
        writer.writerow(["window_seconds", window_seconds])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute FP/FN/TP/TN for a tagged score_stream.json file"
    )
    parser.add_argument("input", type=Path, help="Path to score_stream.json")
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=10.0,
        help="Rolling pre-breach window in seconds (default: 10)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Output JSON report path (default: <input_stem>_confusion_report.json)",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="Output CSV report path (default: <input_stem>_confusion_report.csv)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_json = (
        args.output_json
        if args.output_json is not None
        else input_path.with_name(f"{input_path.stem}_confusion_report.json")
    )
    output_csv = (
        args.output_csv
        if args.output_csv is not None
        else input_path.with_name(f"{input_path.stem}_confusion_report.csv")
    )

    items = load_items(input_path)
    counts = compute_counts(items, args.window_seconds)
    total_rows = len(items)

    write_reports(
        input_path=input_path,
        output_json_path=output_json,
        output_csv_path=output_csv,
        window_seconds=args.window_seconds,
        counts=counts,
        total_rows=total_rows,
    )

    print(f"Input: {input_path}")
    print(f"Window (seconds): {args.window_seconds}")
    print(f"Rows: {total_rows}")
    print(f"TP: {counts['tp']}")
    print(f"FP: {counts['fp']}")
    print(f"FN: {counts['fn']}")
    print(f"TN: {counts['tn']}")
    print(f"JSON report: {output_json}")
    print(f"CSV report: {output_csv}")


if __name__ == "__main__":
    main()
