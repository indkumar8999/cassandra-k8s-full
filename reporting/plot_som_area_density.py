#!/usr/bin/env python3
"""
Plot SOM ``area_map`` as confusion-matrix-style heatmaps (one colored cell per
neuron on the ``som_rows`` x ``som_cols`` grid, default 32x32) from
``som_snapshot.json`` for scenario-a artifact directories.

Batch mode writes all figures under a single output directory (default:
``<artifacts-root>/scenario_a_som_area_matrix_graphs/``) as
``<run-id>_som_area_matrix.png`` plus a multi-panel grid PNG.

Requires: matplotlib, numpy (same stack as plot_som_run.py).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_area_2d(run_dir: Path) -> Tuple[Any, Dict[str, Any], str]:
    """Return (area_2d ndarray, snap dict, run_name)."""
    import numpy as np

    snap_path = run_dir / "som_snapshot.json"
    if not snap_path.exists():
        raise FileNotFoundError(f"Missing {snap_path}")

    snap = _load_json(snap_path)
    if snap.get("error"):
        raise RuntimeError(f"som_snapshot.json not usable: {snap.get('error')}")
    if "area_map" not in snap:
        raise RuntimeError("som_snapshot.json missing area_map")

    area = np.asarray(snap["area_map"], dtype=np.float64)
    if area.ndim != 2:
        raise RuntimeError(f"area_map must be 2-D, got shape {area.shape}")

    exp_r = int(snap.get("som_rows", area.shape[0]))
    exp_c = int(snap.get("som_cols", area.shape[1]))
    if area.shape != (exp_r, exp_c):
        raise RuntimeError(
            f"area_map shape {area.shape} does not match som_rows/som_cols ({exp_r}, {exp_c})"
        )

    return area, snap, run_dir.name


def plot_area_matrix_on_ax(
    ax: Any,
    area: Any,
    title: str,
    *,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    show_axis_labels: bool = True,
) -> Any:
    """Draw confusion-matrix-style heatmap on *ax*; return mappable (im)."""
    import numpy as np

    rows, cols = int(area.shape[0]), int(area.shape[1])
    im = ax.imshow(
        area,
        cmap="viridis",
        interpolation="nearest",
        origin="upper",
        aspect="equal",
        vmin=vmin,
        vmax=vmax,
    )

    # Light grid between cells (confusion-matrix style)
    ax.set_xticks(np.arange(cols + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(rows + 1) - 0.5, minor=True)
    ax.tick_params(which="minor", bottom=False, left=False)
    ax.grid(which="minor", color="0.92", linewidth=0.45)

    tick_step = max(1, cols // 8)
    ax.set_xticks(np.arange(0, cols, tick_step))
    ax.set_yticks(np.arange(0, rows, tick_step))
    if show_axis_labels:
        ax.set_xlabel("column (c)")
        ax.set_ylabel("row (r)")
    ax.set_title(title, fontsize=10)

    return im


def plot_area_matrix_for_run(
    run_dir: Path,
    dpi: int = 150,
    output_dir: Optional[Path] = None,
) -> Path:
    import matplotlib.pyplot as plt

    area, snap, run_name = _load_area_2d(run_dir)
    threshold = snap.get("threshold")

    fig, ax = plt.subplots(figsize=(9.5, 8.5))
    im = plot_area_matrix_on_ax(ax, area, f"SOM area map — {run_name}")

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Inter-neuron distance (area)")
    if threshold is not None:
        cbar.ax.axhline(float(threshold), color="#ff5555", linewidth=2.0, linestyle="--")

    fig.tight_layout()

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"{run_name}_som_area_matrix.png"
    else:
        out = run_dir / "som_area_matrix.png"
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def plot_scenario_a_batch(
    artifacts_root: Path,
    pattern: str = "scenario-a-*",
    combined_name: str = "scenario_a_som_area_matrix_grid.png",
    dpi: int = 150,
    write_combined: bool = True,
    output_dir: Optional[Path] = None,
) -> Tuple[List[Path], Optional[Path]]:
    import matplotlib.pyplot as plt
    import numpy as np

    roots = sorted(p for p in artifacts_root.glob(pattern) if p.is_dir())
    if not roots:
        return [], None

    written: List[Path] = []
    for d in roots:
        snap = d / "som_snapshot.json"
        if not snap.exists():
            continue
        try:
            written.append(plot_area_matrix_for_run(d, dpi=dpi, output_dir=output_dir))
        except Exception as ex:
            print(f"SKIP {d.name}: {ex}", file=sys.stderr)

    combined: Optional[Path] = None
    if write_combined:
        panels: List[Tuple[Path, Any]] = []
        for d in roots:
            snap_path = d / "som_snapshot.json"
            if not snap_path.exists():
                continue
            try:
                area, _, _ = _load_area_2d(d)
                panels.append((d, area))
            except Exception:
                continue

        if panels:
            vmin = float(min(float(a.min()) for _, a in panels))
            vmax = float(max(float(a.max()) for _, a in panels))
            n = len(panels)
            ncols = min(3, n)
            nrows = int(math.ceil(n / ncols))
            fig_w = 4.2 * ncols
            fig_h = 3.8 * nrows
            fig, axes = plt.subplots(nrows, ncols, figsize=(fig_w, fig_h), squeeze=False)
            dest_dir = output_dir if output_dir is not None else artifacts_root
            dest_dir.mkdir(parents=True, exist_ok=True)
            m_last = None
            for idx, (d, area) in enumerate(panels):
                r, c = divmod(idx, ncols)
                ax = axes[r][c]
                m_last = plot_area_matrix_on_ax(
                    ax,
                    area,
                    d.name,
                    vmin=vmin,
                    vmax=vmax,
                    show_axis_labels=True,
                )
            for idx in range(n, nrows * ncols):
                r, c = divmod(idx, ncols)
                axes[r][c].set_visible(False)

            fig.suptitle(
                "SOM area_map (shared color scale) — scenario-a runs",
                fontsize=12,
                y=1.02,
            )
            fig.subplots_adjust(right=0.88)
            if m_last is not None:
                fig.colorbar(
                    m_last,
                    ax=axes.ravel().tolist(),
                    fraction=0.035,
                    pad=0.02,
                    label="Inter-neuron distance (area)",
                )
            fig.tight_layout(rect=[0, 0, 0.86, 0.96])
            combined = dest_dir / combined_name
            fig.savefig(combined, dpi=dpi, bbox_inches="tight")
        plt.close(fig)

    return written, combined


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Confusion-matrix-style heatmaps for SOM area_map in scenario-a artifacts."
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "artifacts",
        help="Directory containing scenario-a-* run folders",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="If set, only plot this single run directory (must contain som_snapshot.json)",
    )
    parser.add_argument("--no-combined", action="store_true", help="Skip multi-panel grid for all scenario-a runs")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write PNGs. Batch default: <artifacts-root>/scenario_a_som_area_matrix_graphs/",
    )
    parser.add_argument(
        "--per-run-dirs",
        action="store_true",
        help="Batch only: write each som_area_matrix.png next to som_snapshot.json instead of --output-dir",
    )
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    root = args.artifacts_root.resolve()
    try:
        if args.run_dir is not None:
            rd = args.run_dir.resolve()
            out_dir = args.output_dir.resolve() if args.output_dir is not None else None
            p = plot_area_matrix_for_run(rd, dpi=args.dpi, output_dir=out_dir)
            print(f"Wrote {p}")
            return
        batch_out: Optional[Path] = None
        if not args.per_run_dirs:
            batch_out = (
                args.output_dir.resolve()
                if args.output_dir is not None
                else root / "scenario_a_som_area_matrix_graphs"
            )
        written, combined = plot_scenario_a_batch(
            root,
            dpi=args.dpi,
            write_combined=not args.no_combined,
            output_dir=batch_out,
        )
        for p in written:
            print(f"Wrote {p}")
        if combined is not None:
            print(f"Wrote {combined}")
        elif not written:
            print("No scenario-a-* directories with som_snapshot.json found.", file=sys.stderr)
            sys.exit(1)
    except Exception as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
