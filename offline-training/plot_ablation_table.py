#!/usr/bin/env python3
"""
Render an ablation-study table using matplotlib.

- Bolds the highest value per "block" (Map size / Neighborhood size / Threshold).
- Values are provided in percent for a single metric (e.g., Accuracy for CPU Pressure).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Tuple


def _fmt_pct(x: float) -> str:
    return f"{x:.2f}%"


def _bold_max_in_block(tbl, row_indices: List[int], metric_col_index: int, values: List[float], setting_col_index: int = 1) -> None:
    if not values:
        return
    max_v = max(values)
    # If ties, bold all maxima.
    for r, v in zip(row_indices, values):
        if v == max_v:
            tbl[(r, metric_col_index)].get_text().set_weight("bold")
            # Also bold the corresponding setting label.
            tbl[(r, setting_col_index)].get_text().set_weight("bold")


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot UBL ablation study table (matplotlib)")
    ap.add_argument("--output", type=Path, default=Path("artifacts/ubl_ablation_table.png"))
    ap.add_argument("--title", type=str, default="UBL Ablation Study")
    ap.add_argument("--metric", type=str, default="Accuracy (CPU Pressure)")
    args = ap.parse_args()

    # Data from your example
    blocks: List[Tuple[str, List[Tuple[str, float]]]] = [
        ("Map", [("25x25", 78.94), ("32x32", 80.82), ("40x40", 78.26)]),
        ("Neighborhood size", [("3", 80.36), ("4", 80.82), ("5", 80.48)]),
        ("Threshold", [("80", 76.16), ("85", 80.82), ("90", 70.98)]),
    ]

    rows: List[List[str]] = []
    for block_name, items in blocks:
        block_disp = block_name.replace("Neighborhood size", "Neighborhood\nsize")
        for i, (label, val) in enumerate(items):
            if block_name == "Map":
                setting = f"{label}"
            elif block_name == "Neighborhood size":
                setting = f"{label}"
            else:
                setting = f"{label}"
            rows.append([block_disp if i == 0 else "", setting, _fmt_pct(val)])

    # Wrap metric header to avoid overflow.
    metric_hdr = (args.metric or "").replace(" (", "\n(").replace(" / ", "\n/ ")
    col_labels = ["", "Setting", metric_hdr]

    import matplotlib.pyplot as plt  # type: ignore

    # Slightly wider figure so long headers don't overflow.
    fig, ax = plt.subplots(figsize=(8.8, 4.2), dpi=180)
    ax.axis("off")

    fig.suptitle(args.title, fontsize=14, fontweight="bold", y=0.98)

    tbl = ax.table(
        cellText=rows,
        colLabels=col_labels,
        colLoc="left",
        cellLoc="left",
        loc="center",
        colWidths=[0.16, 0.56, 0.28],
    )

    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9.5)
    tbl.scale(1, 1.55)

    # Header style
    for c in range(len(col_labels)):
        cell = tbl[(0, c)]
        cell.set_facecolor("#F2F2F2")
        cell.get_text().set_weight("bold")

    # Light borders
    for key, cell in tbl.get_celld().items():
        cell.set_linewidth(0.6)
        cell.set_edgecolor("#D0D0D0")
        cell.get_text().set_wrap(True)

    # Bold maxima per block (in metric column index 2).
    # Table rows are offset by +1 because row 0 is header in mpl tables.
    cursor = 1
    for _block_name, items in blocks:
        vals = [v for _, v in items]
        row_ids = list(range(cursor, cursor + len(items)))
        _bold_max_in_block(tbl, row_ids, 2, vals)
        # Bold the block label cell (Map / Neighborhood size / Threshold)
        tbl[(cursor, 0)].get_text().set_weight("bold")
        cursor += len(items)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=1.0)
    fig.savefig(args.output, bbox_inches="tight")
    print(f"[OK] Wrote table to {args.output}")


if __name__ == "__main__":
    main()

