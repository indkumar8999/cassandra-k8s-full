#!/usr/bin/env python3
"""
Bar chart of model training time.

X axis: SOM / KNN
Y axis: Time (seconds)
Title: "Model Training Time"
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot model training time bar chart")
    ap.add_argument("--som", type=float, default=0.562)
    ap.add_argument("--knn", type=float, default=0.248)
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/model_training_time.png"),
        help="Output PNG path",
    )
    args = ap.parse_args()

    import matplotlib.pyplot as plt  # type: ignore

    labels = ["SOM", "KNN"]
    values = [float(args.som), float(args.knn)]

    plt.figure(figsize=(6.0, 4.2), dpi=160)
    bars = plt.bar(labels, values, color=["#4C78A8", "#F58518"])
    plt.title("Model Training Time")
    plt.ylabel("Time (seconds)")
    plt.grid(axis="y", alpha=0.25)

    ymax = max(values) if values else 0.0
    pad = max(0.02, ymax * 0.04)
    for rect, val in zip(bars, values):
        plt.text(
            rect.get_x() + rect.get_width() / 2.0,
            rect.get_height() + pad,
            f"{val:.3f}s",
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

