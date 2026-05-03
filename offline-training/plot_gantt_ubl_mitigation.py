#!/usr/bin/env python3
"""
Gantt-like timeline comparing "Without UBL" vs "With UBL (And Mitigation)".

X axis: time (seconds)
Y axis: two lanes
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Tuple


def _segments_with_starts(durations: List[float]) -> List[Tuple[float, float]]:
    segs: List[Tuple[float, float]] = []
    t = 0.0
    for d in durations:
        segs.append((t, float(d)))
        t += float(d)
    return segs


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot Gantt-like UBL mitigation timeline")
    ap.add_argument("--output", type=Path, default=Path("artifacts/gantt_ubl_mitigation.png"))
    ap.add_argument("--title", type=str, default="UBL Mitigation Timeline")
    ap.add_argument(
        "--slo-threshold-ms",
        type=float,
        default=200.0,
        help="SLO p95 threshold that defines 'normal' (default: 200ms)",
    )
    ap.add_argument(
        "--label-style",
        choices=["inside", "legend"],
        default="legend",
        help="How to display segment labels (default: legend to avoid overlap)",
    )
    ap.add_argument(
        "--no-initial-spike-marker",
        action="store_true",
        help="Disable the t=0 p95 max spike marker/annotation",
    )
    args = ap.parse_args()

    # Lane 1: Without UBL
    without_total = 90.0
    without_label = "p95=2.09s (max) for 90s"

    # Lane 2: With UBL (And Mitigation)
    # Durations (seconds) and labels (keep user-provided wording/values)
    with_durations = [19.30, 3.24, 40.13, 5.43, 56.00]
    with_labels = [
        "2.09s → 1.0s (19.30s)",
        "1.0s → 500ms (3.24s)",
        "500ms → <200ms (152ms) (40.13s)",
        "Stable normal (5.43s)",
        "Scale down 4→3 nodes (56s)",
    ]

    import matplotlib.pyplot as plt  # type: ignore

    fig, ax = plt.subplots(figsize=(11.5, 4.2), dpi=180)

    lane_height = 0.8
    y_without = 2.0
    y_with = 0.8

    # Without UBL bar
    ax.broken_barh([(0.0, without_total)], (y_without, lane_height), facecolors="#D62728", alpha=0.85)
    if args.label_style == "inside":
        ax.text(
            without_total / 2.0,
            y_without + lane_height / 2.0,
            without_label,
            ha="center",
            va="center",
            fontsize=9,
            color="white",
            fontweight="bold",
        )

    # With UBL bars (multiple segments)
    segs = _segments_with_starts(with_durations)
    # Color palette by "personality" of stages:
    # 1: response/mitigation kick-in (blue), 2: rapid improvement (teal),
    # 3: recovery to normal checkpoint (amber), 4: stable normal (green), 5: scale down (gray).
    colors = ["#4C78A8", "#72B7B2", "#ECA82C", "#54A24B", "#6E6E6E"]
    legend_handles = []
    legend_labels = []
    for i, ((start, dur), label, col) in enumerate(zip(segs, with_labels, colors), start=1):
        ax.broken_barh([(start, dur)], (y_with, lane_height), facecolors=col, alpha=0.90)
        if args.label_style == "inside":
            ax.text(
                start + dur / 2.0,
                y_with + lane_height / 2.0,
                label,
                ha="center",
                va="center",
                fontsize=8.2,
                color="white",
                fontweight="bold",
            )
        else:
            # Put a small step number inside the bar and list details in legend.
            ax.text(
                start + dur / 2.0,
                y_with + lane_height / 2.0,
                str(i),
                ha="center",
                va="center",
                fontsize=10,
                color="white",
                fontweight="bold",
            )
            legend_handles.append(plt.Line2D([0], [0], color=col, lw=8))
            legend_labels.append(f"{i}. {label}")

    if args.label_style == "legend":
        slo_thr = float(args.slo_threshold_ms)
        # Round nicely for display (e.g., 200.0 -> 200).
        slo_thr_s = f"{int(slo_thr)}ms" if abs(slo_thr - int(slo_thr)) < 1e-9 else f"{slo_thr:g}ms"
        legend_handles.insert(0, plt.Line2D([0], [0], color="#D62728", lw=8))
        legend_labels.insert(0, f"Without UBL: {without_label} (normal ≤ {slo_thr_s})")
        ax.legend(
            legend_handles,
            legend_labels,
            loc="upper left",
            bbox_to_anchor=(1.01, 1.0),
            borderaxespad=0.0,
            frameon=True,
            fontsize=8.5,
        )

    # Axes / labels
    ax.set_ylim(0.4, 3.2)
    ax.set_xlim(0.0, max(without_total, sum(with_durations)) * 1.02)
    ax.set_yticks([y_without + lane_height / 2.0, y_with + lane_height / 2.0])
    ax.set_yticklabels(["Without UBL", "With UBL\n(And Mitigation)"])
    ax.set_xlabel("Time (seconds)")
    # Include threshold in the title so it survives cropping/legend changes.
    slo_thr = float(args.slo_threshold_ms)
    slo_thr_s = f"{int(slo_thr)}ms" if abs(slo_thr - int(slo_thr)) < 1e-9 else f"{slo_thr:g}ms"
    ax.set_title(f"{args.title}  (SLO normal: p95 ≤ {slo_thr_s})")
    ax.grid(axis="x", alpha=0.25)

    # Single visual cue: when UBL returns the system to "normal" (≤ threshold).
    # This is the boundary between step 3 (improving) and step 4 (stable normal).
    t_normal = float(with_durations[0] + with_durations[1] + with_durations[2])
    ax.axvline(t_normal, color="#54A24B", linestyle="-", linewidth=2.0, alpha=0.95, zorder=6)
    ax.text(
        t_normal + max(0.4, ax.get_xlim()[1] * 0.006),
        y_with + lane_height + 0.03,
        f"Normal (p95 ≤ {slo_thr_s})",
        ha="left",
        va="bottom",
        fontsize=9,
        color="#2E6F3E",
        fontweight="bold",
    )

    # Explicitly mark the initial SLO spike event at t=0.
    if not args.no_initial_spike_marker:
        spike_color = "#B22222"  # dark red
        ax.axvline(0.0, color=spike_color, linestyle="--", linewidth=1.4, alpha=0.95, zorder=5)
        # Annotate near the top lane so it doesn't clash with legend (legend is outside).
        ax.annotate(
            "t=0: p95 SLO spikes to max (2.09s)",
            xy=(0.0, y_without + lane_height * 0.95),
            xytext=(max(2.0, ax.get_xlim()[1] * 0.10), y_without + lane_height * 1.35),
            textcoords="data",
            ha="left",
            va="bottom",
            fontsize=9,
            color=spike_color,
            fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=spike_color, lw=1.2),
        )

    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, bbox_inches="tight")
    print(f"[OK] Wrote chart to {args.output}")


if __name__ == "__main__":
    main()

