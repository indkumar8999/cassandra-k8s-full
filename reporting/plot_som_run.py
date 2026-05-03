#!/usr/bin/env python3
"""
Plot SOM area map and BMU scatter (by phase) from a scenario run directory.

Requires: matplotlib, artifacts som_snapshot.json + score_stream.json from run_scenario.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


PHASE_COLORS = {
    "normal": "#1f77b4",
    "load": "#2ca02c",
    "chaos": "#d62728",
    "cooldown": "#ff7f0e",
    "unknown": "#7f7f7f",
}


def plot_run(run_dir: Path) -> Tuple[Path, Path, Path]:
    import matplotlib.pyplot as plt
    import numpy as np

    snap_path = run_dir / "som_snapshot.json"
    stream_path = run_dir / "score_stream.json"
    if not snap_path.exists():
        raise FileNotFoundError(f"Missing {snap_path}")
    if not stream_path.exists():
        raise FileNotFoundError(f"Missing {stream_path}")

    snap = _load_json(snap_path)
    if snap.get("error"):
        raise RuntimeError(f"som_snapshot.json not usable: {snap.get('error')}")

    area = np.array(snap["area_map"], dtype=np.float64)
    weights = np.array(snap["weights"], dtype=np.float64)
    rows, cols = int(snap["som_rows"]), int(snap["som_cols"])

    stream = _load_json(stream_path)
    items: List[Dict[str, Any]] = stream.get("items", [])

    # --- Figure 1: area map (U-matrix style) + neuron weight norm per cell (side panel optional skip)
    fig1, ax1 = plt.subplots(figsize=(8, 7))
    im = ax1.imshow(area, origin="upper", aspect="equal", cmap="viridis")
    plt.colorbar(im, ax=ax1, fraction=0.046, label="Inter-neuron distance (area)")
    ax1.set_title("Trained SOM — area map (U-matrix)")
    ax1.set_xlabel("column")
    ax1.set_ylabel("row")
    out1 = run_dir / "som_area_map.png"
    fig1.tight_layout()
    fig1.savefig(out1, dpi=150)
    plt.close(fig1)

    # --- Figure 2: BMUs by phase (chaos highlighted larger)
    fig2, ax2 = plt.subplots(figsize=(8, 7))
    ax2.imshow(area, origin="upper", aspect="equal", cmap="Greys", alpha=0.35)
    ax2.set_xlim(-0.5, cols - 0.5)
    ax2.set_ylim(rows - 0.5, -0.5)

    for phase, color in PHASE_COLORS.items():
        xs: List[float] = []
        ys: List[float] = []
        for it in items:
            if it.get("phase") != phase:
                continue
            bmu = it.get("bmu")
            if not bmu or len(bmu) != 2:
                continue
            br, bc = int(bmu[0]), int(bmu[1])
            xs.append(bc)
            ys.append(br)
        if not xs:
            continue
        s = 36 if phase == "chaos" else 12
        alpha = 0.85 if phase == "chaos" else 0.35
        ax2.scatter(xs, ys, c=color, s=s, alpha=alpha, label=phase, edgecolors="none")

    ax2.set_title("BMU hits by phase (chaos = larger markers)")
    ax2.set_xlabel("column (BMU c)")
    ax2.set_ylabel("row (BMU r)")
    ax2.legend(loc="upper right", fontsize=8)
    out2 = run_dir / "som_bmu_by_phase.png"
    fig2.tight_layout()
    fig2.savefig(out2, dpi=150)
    plt.close(fig2)

    # --- Figure 3: optional — weight vector norm heatmap (mean L2 of each neuron's weight vector)
    fig3, ax3 = plt.subplots(figsize=(8, 7))
    wnorm = np.linalg.norm(weights, axis=2)
    im3 = ax3.imshow(wnorm, origin="upper", aspect="equal", cmap="magma")
    plt.colorbar(im3, ax=ax3, fraction=0.046, label="||w||")
    ax3.set_title("SOM neuron weight magnitude (per cell)")
    ax3.set_xlabel("column")
    ax3.set_ylabel("row")
    out3 = run_dir / "som_weight_norm.png"
    fig3.tight_layout()
    fig3.savefig(out3, dpi=150)
    plt.close(fig3)

    return out1, out2, out3


def main():
    parser = argparse.ArgumentParser(description="Plot SOM artifacts for one run directory.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Path to scenario run (e.g. artifacts/scenario-*)")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    try:
        p1, p2, p3 = plot_run(run_dir)
    except Exception as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
    print(f"Wrote {p1}")
    print(f"Wrote {p2}")
    print(f"Wrote {p3}")


if __name__ == "__main__":
    main()
