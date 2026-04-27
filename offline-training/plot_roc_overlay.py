#!/usr/bin/env python3
"""Overlay ROC curves for multiple SOM snapshots on one plot.

Typical use:
- After running `eval_all_ubl_snapshots.py` which writes <out-dir>/summary.json
- This script reads the snapshot paths from that summary, recomputes ROC curves on the given dataset,
  and saves a single PNG with all curves overlaid.

Why recompute?
- The sweep writes PNGs per snapshot but doesn't persist raw fpr/tpr arrays.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from eval_som_roc import compute_scores, load_labeled_samples, load_snapshot


def _load_snapshot_paths(summary_path: Path, max_curves: int | None) -> List[Path]:
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("summary.json must be a list")

    paths: List[Path] = []
    for r in data:
        if not isinstance(r, dict):
            continue
        if "auc" not in r:
            continue
        p = r.get("snapshot")
        if not isinstance(p, str):
            continue
        paths.append(Path(p))
        if max_curves is not None and len(paths) >= max_curves:
            break
    if not paths:
        raise ValueError("No usable snapshot entries with 'auc' found in summary")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot ROC overlay for all SOM snapshots")
    parser.add_argument(
        "--samples-json",
        required=True,
        help="Path to labeled samples JSON (same used for sweep)",
    )
    parser.add_argument(
        "--summary-json",
        required=True,
        help="Path to sweep summary.json (from eval_all_ubl_snapshots.py)",
    )
    parser.add_argument(
        "--out-png",
        required=True,
        help="Output PNG path for overlay plot",
    )
    parser.add_argument(
        "--max-curves",
        type=int,
        default=0,
        help="Optional limit: plot only top-N snapshots from summary (0 means all)",
    )

    args = parser.parse_args()

    samples_path = Path(args.samples_json)
    summary_path = Path(args.summary_json)
    out_png = Path(args.out_png)

    max_curves = None if args.max_curves == 0 else int(args.max_curves)

    sample_dicts, y_true = load_labeled_samples(samples_path)
    snapshot_paths = _load_snapshot_paths(summary_path, max_curves=max_curves)

    from sklearn.metrics import roc_auc_score, roc_curve  # type: ignore

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # type: ignore

    plt.figure(figsize=(7, 7))

    # Plot each ROC. Use a light alpha so overlaps are visible.
    for snap_path in snapshot_paths:
        snap = load_snapshot(snap_path)
        y_score = compute_scores(snap, sample_dicts)
        auc = float(roc_auc_score(y_true, y_score))
        fpr, tpr, _ = roc_curve(y_true, y_score)
        plt.plot(fpr, tpr, linewidth=1.2, alpha=0.55, label=f"{snap_path.name} (AUC={auc:.3f})")

    plt.plot([0, 1], [0, 1], linestyle="--", color="black", linewidth=1, alpha=0.7)
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    title = "ROC Overlay"
    if max_curves is not None:
        title += f" (top {max_curves})"
    plt.title(title)

    # Many labels -> small font + multi-column legend.
    plt.legend(fontsize=7, loc="lower right", ncol=1, framealpha=0.9)
    plt.grid(True, alpha=0.25)
    plt.tight_layout()

    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=150)
    plt.close()

    print(f"[OK] Wrote overlay: {out_png} (curves={len(snapshot_paths)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
