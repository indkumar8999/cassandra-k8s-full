#!/usr/bin/env python3
"""
Line chart: lead time vs K (consecutive alarm count).
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot lead time ablation (K vs lead time)")
    ap.add_argument("--output", type=Path, default=Path("artifacts/lead_time_ablation_k.png"))
    ap.add_argument("--title", type=str, default="Lead Time Ablation")
    args = ap.parse_args()

    # Provided data points
    k_vals = [5, 7, 9]
    lead_sec = [9.50, 8.42, 7.35]

    import matplotlib.pyplot as plt  # type: ignore

    plt.figure(figsize=(6.5, 4.5), dpi=160)
    plt.plot(k_vals, lead_sec, marker="o", linewidth=2.0, color="#4C78A8")
    plt.title(args.title)
    plt.xlabel("K (Consecutive Alarm Count)")
    plt.ylabel("Lead time (seconds)")
    plt.grid(True, alpha=0.25)
    plt.ylim(bottom=0)

    for k, v in zip(k_vals, lead_sec):
        plt.text(k, v + max(0.2, max(lead_sec) * 0.01), f"{v:.2f}s", ha="center", va="bottom", fontsize=10)

    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output)
    print(f"[OK] Wrote line chart to {args.output}")


if __name__ == "__main__":
    main()

