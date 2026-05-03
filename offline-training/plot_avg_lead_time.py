#!/usr/bin/env python3
"""
Bar chart of average lead time.

X axis: CPU / Memory / Disk
Y axis: Time (seconds)
Title: "Average lead time"
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot average lead time bar chart")
    ap.add_argument("--cpu", type=float, default=9.5)
    ap.add_argument("--memory", type=float, default=0.0)
    ap.add_argument("--disk", type=float, default=15.65)
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/avg_lead_time.png"),
        help="Output PNG path",
    )
    args = ap.parse_args()

    import matplotlib.pyplot as plt  # type: ignore

    labels = ["CPU", "Memory", "Disk"]
    values = [float(args.cpu), float(args.memory), float(args.disk)]

    plt.figure(figsize=(6.5, 4.5), dpi=160)
    bars = plt.bar(labels, values, color=["#4C78A8", "#F58518", "#54A24B"])
    plt.title("Average lead time")
    plt.ylabel("Time (seconds)")
    plt.xlabel("cpu, memory, disk")
    plt.grid(axis="y", alpha=0.25)

    ymax = max(values) if values else 0.0
    pad = max(0.2, ymax * 0.02)
    for rect, val in zip(bars, values):
        plt.text(
            rect.get_x() + rect.get_width() / 2.0,
            rect.get_height() + pad,
            f"{val:.2f}s",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    plt.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output)
    print(f"[OK] Wrote chart to {args.output}")


if __name__ == "__main__":
    main()

