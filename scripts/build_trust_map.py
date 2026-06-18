#!/usr/bin/env python3
"""Build 2D spatial trust map C(x,y) from trust_log.csv + trajectory TUM.

Formula (experiment plan §12):
  C(p) = sum_t w_t * c(t) / sum_t w_t
  w_t = exp( -||p - p_hat_t||^2 / (2*r^2) )

Fast mode (--method bin): binning c(t) at trajectory xy + optional Gaussian smooth.

Outputs in --out-dir (default: <result>/trust_map/):
  trust_map.png       — heatmap + trajectory overlay
  trust_along_path.png — c(t) vs time and path colored by c
  trust_grid.npz      — x_centers, y_centers, C, counts
  meta.json           — parameters and statistics
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.colors import Normalize
except ImportError as exc:
    raise SystemExit("matplotlib required: pip install matplotlib") from exc

try:
    from scipy.ndimage import gaussian_filter
except ImportError:
    gaussian_filter = None  # type: ignore


def load_trajectory(path: Path) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        rows.append(
            {
                "t": float(parts[0]),
                "x": float(parts[1]),
                "y": float(parts[2]),
                "z": float(parts[3]),
            }
        )
    if not rows:
        raise ValueError(f"No poses in trajectory: {path}")
    return pd.DataFrame(rows).sort_values("t").reset_index(drop=True)


def load_trust_log(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "timestamp" not in df.columns or "c" not in df.columns:
        raise ValueError(f"trust_log must contain timestamp,c columns: {path}")
    df = df.rename(columns={"timestamp": "t"})
    df = df.sort_values("t").reset_index(drop=True)
    return df


def _timestamps_usable(trust: pd.DataFrame, traj: pd.DataFrame) -> bool:
    """Detect scientific-notation CSV corruption (all timestamps collapse to one value)."""
    n = len(trust)
    if n < 2:
        return True
    n_unique = trust["t"].nunique()
    if n_unique <= max(1, n // 20):
        return False
    span = float(trust["t"].max() - trust["t"].min())
    if span < 1e-2 and n > 10:
        return False
    # trust timestamps should overlap trajectory time range
    t_lo, t_hi = float(traj["t"].min()), float(traj["t"].max())
    margin = max(5.0, 0.05 * (t_hi - t_lo))
    if float(trust["t"].max()) < t_lo - margin or float(trust["t"].min()) > t_hi + margin:
        return False
    return True


def _align_by_index(trust: pd.DataFrame, traj: pd.DataFrame) -> pd.DataFrame:
    """Fallback: map trust samples evenly along trajectory (same run, no usable timestamps)."""
    n, m = len(trust), len(traj)
    idx = np.linspace(0, m - 1, n).round().astype(int)
    traj_sel = traj.iloc[idx].reset_index(drop=True)
    merged = trust.copy()
    merged["t_traj"] = traj_sel["t"].to_numpy()
    merged["x"] = traj_sel["x"].to_numpy()
    merged["y"] = traj_sel["y"].to_numpy()
    merged["z"] = traj_sel["z"].to_numpy()
    merged["align_method"] = "index"
    return merged


def align_trust_trajectory(
    trust: pd.DataFrame,
    traj: pd.DataFrame,
    *,
    max_dt: float = 0.1,
) -> pd.DataFrame:
    """Match trust samples to trajectory poses by timestamp, or by index if timestamps unusable."""
    if not _timestamps_usable(trust, traj):
        return _align_by_index(trust, traj)

    merged = pd.merge_asof(
        trust,
        traj[["t", "x", "y", "z"]],
        on="t",
        direction="nearest",
        tolerance=max_dt,
    )
    merged = merged.dropna(subset=["x", "y"])
    if len(merged) >= max(1, int(0.8 * len(trust))):
        merged = merged.copy()
        merged["align_method"] = "timestamp"
        merged["t_traj"] = merged["t"]
        return merged

    return _align_by_index(trust, traj)


def _grid_edges(
    x: np.ndarray,
    y: np.ndarray,
    *,
    cell_size: float | None,
    grid_n: int,
    margin: float,
) -> tuple[np.ndarray, np.ndarray]:
    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = float(y.min()), float(y.max())
    dx = xmax - xmin
    dy = ymax - ymin
    pad_x = max(margin, 0.05 * dx if dx > 0 else margin)
    pad_y = max(margin, 0.05 * dy if dy > 0 else margin)
    xmin -= pad_x
    xmax += pad_x
    ymin -= pad_y
    ymax += pad_y

    if cell_size is not None and cell_size > 0:
        nx = max(8, int(np.ceil((xmax - xmin) / cell_size)))
        ny = max(8, int(np.ceil((ymax - ymin) / cell_size)))
    else:
        span = max(xmax - xmin, ymax - ymin, 1e-3)
        cs = span / grid_n
        nx = max(8, int(np.ceil((xmax - xmin) / cs)))
        ny = max(8, int(np.ceil((ymax - ymin) / cs)))

    x_edges = np.linspace(xmin, xmax, nx + 1)
    y_edges = np.linspace(ymin, ymax, ny + 1)
    return x_edges, y_edges


def build_map_binning(
    x: np.ndarray,
    y: np.ndarray,
    c: np.ndarray,
    *,
    x_edges: np.ndarray,
    y_edges: np.ndarray,
    smooth_sigma: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sum_c, _, _ = np.histogram2d(x, y, bins=[x_edges, y_edges], weights=c)
    count, _, _ = np.histogram2d(x, y, bins=[x_edges, y_edges])
    with np.errstate(invalid="ignore"):
        grid = np.divide(sum_c, count, where=count > 0, out=np.full_like(sum_c, np.nan))

    if smooth_sigma > 0 and gaussian_filter is not None:
        mask = np.isfinite(grid)
        if mask.any():
            filled = np.where(mask, grid, 0.0)
            weights = mask.astype(float)
            sm_c = gaussian_filter(filled, sigma=smooth_sigma, mode="nearest")
            sm_w = gaussian_filter(weights, sigma=smooth_sigma, mode="nearest")
            with np.errstate(invalid="ignore"):
                grid = np.divide(sm_c, sm_w, where=sm_w > 1e-9, out=np.full_like(sm_c, np.nan))

    x_centers = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
    return x_centers, y_centers, grid.T  # shape (len(y), len(x)) for imshow


def build_map_kernel(
    x: np.ndarray,
    y: np.ndarray,
    c: np.ndarray,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    radius: float,
) -> np.ndarray:
    """Exact kernel accumulation on grid centers (can be slow on large grids)."""
    xx, yy = np.meshgrid(x_centers, y_centers)
    acc = np.zeros_like(xx, dtype=float)
    wsum = np.zeros_like(xx, dtype=float)
    r2 = max(radius * radius, 1e-6)
    cutoff = (3.0 * radius) ** 2

    for xi, yi, ci in zip(x, y, c, strict=False):
        dx = xx - xi
        dy = yy - yi
        dist2 = dx * dx + dy * dy
        w = np.exp(-dist2 / (2.0 * r2))
        w[dist2 > cutoff] = 0.0
        acc += w * ci
        wsum += w

    with np.errstate(invalid="ignore"):
        grid = np.divide(acc, wsum, where=wsum > 0, out=np.full_like(acc, np.nan))
    return grid


def build_trust_map(
    merged: pd.DataFrame,
    *,
    method: str = "bin",
    cell_size: float | None = None,
    grid_n: int = 48,
    margin: float = 0.5,
    radius: float = 1.0,
    smooth_sigma: float = 1.0,
) -> dict[str, Any]:
    x = merged["x"].to_numpy(dtype=float)
    y = merged["y"].to_numpy(dtype=float)
    c = merged["c"].to_numpy(dtype=float)

    x_edges, y_edges = _grid_edges(x, y, cell_size=cell_size, grid_n=grid_n, margin=margin)
    x_centers = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])

    if method == "kernel":
        grid = build_map_kernel(x, y, c, x_centers=x_centers, y_centers=y_centers, radius=radius)
        count = np.zeros_like(grid)
    else:
        x_centers, y_centers, grid = build_map_binning(
            x, y, c,
            x_edges=x_edges,
            y_edges=y_edges,
            smooth_sigma=smooth_sigma if method == "bin" else 0.0,
        )
        _, _, count = build_map_binning(
            x, y, np.ones_like(c),
            x_edges=x_edges,
            y_edges=y_edges,
            smooth_sigma=0.0,
        )

    valid = np.isfinite(grid)
    stats = {
        "n_samples": int(len(merged)),
        "grid_shape": [int(grid.shape[0]), int(grid.shape[1])],
        "c_mean": float(np.nanmean(c)),
        "c_min": float(np.nanmin(c)) if valid.any() else None,
        "c_max": float(np.nanmax(c)) if valid.any() else None,
        "c_map_mean": float(np.nanmean(grid)) if valid.any() else None,
    }
    return {
        "x_centers": x_centers,
        "y_centers": y_centers,
        "C": grid,
        "counts": count,
        "stats": stats,
        "trajectory": merged,
    }


def _plot_map(
    result: dict[str, Any],
    *,
    out_png: Path,
    c_threshold: float,
    title: str,
) -> None:
    x_centers = result["x_centers"]
    y_centers = result["y_centers"]
    grid = result["C"]
    traj = result["trajectory"]

    dx = (x_centers[1] - x_centers[0]) if len(x_centers) > 1 else 0.5
    dy = (y_centers[1] - y_centers[0]) if len(y_centers) > 1 else 0.5
    extent = [
        x_centers[0] - dx / 2,
        x_centers[-1] + dx / 2,
        y_centers[0] - dy / 2,
        y_centers[-1] + dy / 2,
    ]

    fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad(color="#dddddd")
    im = ax.imshow(
        grid,
        origin="lower",
        extent=extent,
        aspect="equal",
        cmap=cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="bilinear",
    )
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("C(x, y) — trust")

    tx = traj["x"].to_numpy()
    ty = traj["y"].to_numpy()
    ax.plot(tx, ty, color="white", linewidth=1.2, alpha=0.85, label="trajectory")
    ax.plot(tx[0], ty[0], "o", color="lime", markersize=7, label="start")
    ax.plot(tx[-1], ty[-1], "s", color="red", markersize=6, label="end")

    if np.isfinite(grid).any() and c_threshold > 0:
        ax.contour(
            x_centers,
            y_centers,
            grid,
            levels=[c_threshold],
            colors=["#ff4444"],
            linewidths=1.5,
            linestyles="--",
        )
        ax.plot([], [], color="#ff4444", linestyle="--", label=f"low trust < {c_threshold:.2f}")

    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.25, color="white", linewidth=0.5)
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def _plot_along_path(result: dict[str, Any], *, out_png: Path, title: str) -> None:
    traj = result["trajectory"]
    t = traj["t"].to_numpy()
    c = traj["c"].to_numpy()
    t0 = t[0]
    t_rel = t - t0

    fig, axes = plt.subplots(2, 1, figsize=(9, 6), constrained_layout=True, sharex=False)

    axes[0].plot(t_rel, c, color="#2a6fdb", linewidth=1.0)
    axes[0].axhline(0.4, color="#cc3333", linestyle="--", linewidth=1, alpha=0.7, label="c=0.4")
    axes[0].set_ylabel("c(t)")
    axes[0].set_xlabel("time since start [s]")
    axes[0].set_ylim(0, 1.05)
    axes[0].set_title(f"{title} — c(t) along run")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="lower right", fontsize=8)

    x = traj["x"].to_numpy()
    y = traj["y"].to_numpy()
    points = np.column_stack([x, y]).reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    norm = Normalize(vmin=0.0, vmax=1.0)
    lc = LineCollection(segments, cmap="viridis", norm=norm, linewidths=2.0)
    lc.set_array(0.5 * (c[:-1] + c[1:]))
    axes[1].add_collection(lc)
    axes[1].autoscale()
    axes[1].plot(x[0], y[0], "o", color="lime", markersize=7)
    axes[1].plot(x[-1], y[-1], "s", color="red", markersize=6)
    axes[1].set_xlabel("x [m]")
    axes[1].set_ylabel("y [m]")
    axes[1].set_aspect("equal", adjustable="box")
    axes[1].set_title("Trajectory colored by c(t)")
    cb = fig.colorbar(lc, ax=axes[1], fraction=0.046, pad=0.04)
    cb.set_label("c(t)")
    axes[1].grid(True, alpha=0.3)

    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def run_build(
    *,
    trust_path: Path,
    traj_path: Path,
    out_dir: Path,
    method: str = "bin",
    cell_size: float | None = None,
    grid_n: int = 48,
    margin: float = 0.5,
    radius: float = 1.0,
    smooth_sigma: float = 1.0,
    max_dt: float = 0.1,
    c_threshold: float = 0.4,
    title: str = "",
) -> Path:
    trust = load_trust_log(trust_path)
    traj = load_trajectory(traj_path)
    merged = align_trust_trajectory(trust, traj, max_dt=max_dt)

    result = build_trust_map(
        merged,
        method=method,
        cell_size=cell_size,
        grid_n=grid_n,
        margin=margin,
        radius=radius,
        smooth_sigma=smooth_sigma,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    map_png = out_dir / "trust_map.png"
    path_png = out_dir / "trust_along_path.png"
    plot_title = title or trust_path.parent.name

    _plot_map(result, out_png=map_png, c_threshold=c_threshold, title=f"Trust map — {plot_title}")
    _plot_along_path(result, out_png=path_png, title=plot_title)

    np.savez_compressed(
        out_dir / "trust_grid.npz",
        x_centers=result["x_centers"],
        y_centers=result["y_centers"],
        C=result["C"],
        counts=result["counts"],
    )

    meta = {
        "trust_log": str(trust_path.resolve()),
        "trajectory": str(traj_path.resolve()),
        "align_method": str(merged["align_method"].iloc[0]) if "align_method" in merged.columns else "unknown",
        "method": method,
        "cell_size_m": cell_size,
        "grid_n": grid_n,
        "margin_m": margin,
        "kernel_radius_m": radius,
        "smooth_sigma": smooth_sigma,
        "max_dt_s": max_dt,
        "c_threshold": c_threshold,
        "stats": result["stats"],
        "outputs": {
            "trust_map_png": str(map_png),
            "trust_along_path_png": str(path_png),
            "trust_grid_npz": str(out_dir / "trust_grid.npz"),
        },
    }
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if meta["align_method"] == "index":
        print(
            f"  note: trust_log timestamps unusable (scientific notation in CSV) — aligned by index",
            file=sys.stderr,
        )
    return map_png


def _find_result_dirs(root: Path) -> list[Path]:
    dirs: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name == "batches":
            continue
        if (child / "trust_log.csv").is_file() and (child / "trajectory_tum.txt").is_file():
            dirs.append(child)
    return dirs


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 2D trust map from adaptive run outputs")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--result-dir", type=Path, help="Single run directory with trust_log + trajectory")
    src.add_argument("--trust", type=Path, help="trust_log.csv path")
    src.add_argument("--scan", type=Path, help="Scan results root for adaptive runs")
    parser.add_argument("--traj", type=Path, help="trajectory_tum.txt (with --trust)")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory (default: <result>/trust_map)")
    parser.add_argument("--method", choices=["bin", "kernel"], default="bin", help="bin=fast grid+smooth, kernel=exact formula")
    parser.add_argument("--cell-size", type=float, default=None, help="Grid cell size [m] (overrides --grid-n)")
    parser.add_argument("--grid-n", type=int, default=48, help="Approx cells along longest side")
    parser.add_argument("--margin", type=float, default=0.5, help="Border margin [m]")
    parser.add_argument("--radius", type=float, default=1.0, help="Kernel radius r [m] for --method kernel")
    parser.add_argument("--smooth-sigma", type=float, default=1.0, help="Gaussian smooth on grid (bin mode)")
    parser.add_argument("--max-dt", type=float, default=0.1, help="Max |t_trust - t_pose| for alignment [s]")
    parser.add_argument("--c-threshold", type=float, default=0.4, help="Contour for low-trust zones")
    parser.add_argument("--title", default="", help="Plot title")
    args = parser.parse_args()

    jobs: list[tuple[Path, Path, Path, str]] = []

    if args.scan:
        for rd in _find_result_dirs(args.scan.resolve()):
            jobs.append((rd / "trust_log.csv", rd / "trajectory_tum.txt", rd / "trust_map", rd.name))
    elif args.result_dir:
        rd = args.result_dir.resolve()
        jobs.append((rd / "trust_log.csv", rd / "trajectory_tum.txt", args.out_dir or rd / "trust_map", args.title or rd.name))
    elif args.trust and args.traj:
        out = args.out_dir or args.trust.parent / "trust_map"
        jobs.append((args.trust.resolve(), args.traj.resolve(), out, args.title))
    else:
        parser.error("Specify --result-dir, (--trust and --traj), or --scan")
        return 2

    if not jobs:
        print("No adaptive result directories found.", file=sys.stderr)
        return 1

    last_png: Path | None = None
    for trust_p, traj_p, out_d, title in jobs:
        if not trust_p.is_file():
            print(f"Skip (no trust log): {trust_p.parent}", file=sys.stderr)
            continue
        if not traj_p.is_file():
            print(f"Skip (no trajectory): {traj_p.parent}", file=sys.stderr)
            continue
        try:
            last_png = run_build(
                trust_path=trust_p,
                traj_path=traj_p,
                out_dir=out_d.resolve(),
                method=args.method,
                cell_size=args.cell_size,
                grid_n=args.grid_n,
                margin=args.margin,
                radius=args.radius,
                smooth_sigma=args.smooth_sigma,
                max_dt=args.max_dt,
                c_threshold=args.c_threshold,
                title=title,
            )
            print(f"Trust map: {last_png}")
        except Exception as exc:
            print(f"Failed {trust_p.parent}: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
