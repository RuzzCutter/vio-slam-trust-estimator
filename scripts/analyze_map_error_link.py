#!/usr/bin/env python3
"""Link the confidence map C(p) with the local trajectory error.

Per run: poses are binned into square cells; each cell gets mean c(t) and mean local
error growth |e(t+dt) - e(t)| (an RPE-like quantity, unlike the absolute per-pose ATE
which accumulates past drift). Correlation is computed across cells, then aggregated
per (sequence, degradation) cell of the batch.

Examples:
  python3 scripts/analyze_map_error_link.py --batch datasets/results/batches/f_euroc_20260907_223705
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("matplotlib required: pip install matplotlib") from exc

from scipy import stats as sps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from build_trust_map import load_trajectory, load_trust_log  # noqa: E402
from run_results import degrade_spec_to_label, load_batch_manifest  # noqa: E402

DEFAULT_BATCH = ROOT / "datasets" / "results" / "batches" / "f_euroc_20260907_223705"
DEFAULT_OUT = ROOT / "paper_tables" / "f_corr"


def nearest(values: np.ndarray, targets: np.ndarray, max_dt: float) -> np.ndarray:
    """Index of the closest element of values for each target, or -1 if farther than max_dt."""
    idx = np.searchsorted(values, targets)
    idx = np.clip(idx, 1, values.size - 1)
    left = values[idx - 1]
    right = values[idx]
    pick = np.where(np.abs(targets - left) <= np.abs(right - targets), idx - 1, idx)
    bad = np.abs(values[pick] - targets) > max_dt
    pick[bad] = -1
    return pick


def local_growth(t: np.ndarray, e: np.ndarray, horizon_s: float) -> np.ndarray:
    """|e(t+horizon) - e(t)|, NaN where the horizon runs past the end."""
    ahead = nearest(t, t + horizon_s, max_dt=horizon_s * 0.5)
    out = np.full(t.size, np.nan)
    ok = ahead >= 0
    out[ok] = np.abs(e[ahead[ok]] - e[ok])
    return out


def analyze_run(
    result_dir: Path,
    *,
    cell_m: float,
    min_samples: int,
    horizon_s: float,
    max_dt: float,
) -> dict[str, Any]:
    out: dict[str, Any] = {"result_dir": result_dir.name}
    traj_path = result_dir / "trajectory_tum.txt"
    trust_path = result_dir / "trust_log.csv"
    err_path = result_dir / "metrics" / "pose_errors.csv"
    if not (traj_path.is_file() and trust_path.is_file() and err_path.is_file()):
        out["error"] = "missing inputs"
        return out

    traj = load_trajectory(traj_path)
    trust = load_trust_log(trust_path)
    err = np.genfromtxt(err_path, delimiter=",", names=True)
    te = np.asarray(err["t"], dtype=float)
    ee = np.asarray(err["e_ate_m"], dtype=float)
    order = np.argsort(te)
    te, ee = te[order], ee[order]

    growth = local_growth(te, ee, horizon_s)
    tt = trust["t"].to_numpy(dtype=float)
    cc = trust["c"].to_numpy(dtype=float)
    tx = traj["t"].to_numpy(dtype=float)
    px = traj["x"].to_numpy(dtype=float)
    py = traj["y"].to_numpy(dtype=float)

    i_pose = nearest(tx, te, max_dt)
    i_c = nearest(tt, te, max_dt)
    ok = (i_pose >= 0) & (i_c >= 0) & np.isfinite(growth)
    if ok.sum() < 20:
        out["error"] = "too few aligned samples"
        return out

    x = px[i_pose[ok]]
    y = py[i_pose[ok]]
    c = cc[i_c[ok]]
    g = growth[ok]

    ix = np.floor(x / cell_m).astype(int)
    iy = np.floor(y / cell_m).astype(int)
    keys = ix.astype(np.int64) * 100003 + iy.astype(np.int64)
    cell_c: list[float] = []
    cell_g: list[float] = []
    for key in np.unique(keys):
        sel = keys == key
        if sel.sum() < min_samples:
            continue
        cell_c.append(float(np.mean(c[sel])))
        cell_g.append(float(np.mean(g[sel])))
    if len(cell_c) < 5:
        out["error"] = "too few cells"
        return out

    arr_c = np.asarray(cell_c)
    arr_g = np.asarray(cell_g)
    pear = sps.pearsonr(arr_c, arr_g)
    spear = sps.spearmanr(arr_c, arr_g)
    out.update(
        {
            "n_samples": int(ok.sum()),
            "n_cells": len(cell_c),
            "pearson_r": float(pear.statistic),
            "pearson_p": float(pear.pvalue),
            "r_squared": float(pear.statistic**2),
            "spearman_r": float(spear.statistic),
            "spearman_p": float(spear.pvalue),
            "cell_c": cell_c,
            "cell_growth_m": cell_g,
        }
    )
    return out


def fmt(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def write_table(cells: list[dict[str, Any]], params: dict[str, Any], path: Path) -> None:
    lines = [
        "## Связь карты достоверности C(p) с локальной ошибкой траектории",
        "",
        f"Ячейка карты {params['cell_m']} м, не менее {params['min_samples']} поз в ячейке; "
        f"локальная ошибка — прирост |e(t+{params['horizon_s']} с) − e(t)| после выравнивания Sim(3).",
        "",
        "| Последовательность | Условие | Прогонов | Ячеек (медиана) | Медиана r | Медиана R² | Медиана Спирмена | Доля p<0,05 |",
        "|--------------------|---------|----------|-----------------|-----------|------------|------------------|-------------|",
    ]
    for cell in cells:
        lines.append(
            f"| {cell['seq']} | {cell['degrade_label']} | {cell['n_runs']} | {cell['n_cells_med']} "
            f"| {fmt(cell['pearson_r_med'])} | {fmt(cell['r_squared_med'])} "
            f"| {fmt(cell['spearman_r_med'])} | {fmt(cell['frac_p_lt_05'], 2)} |"
        )
    lines.append("")
    return path.write_text("\n".join(lines), encoding="utf-8")


def plot_scatter(cells: list[dict[str, Any]], runs: list[dict[str, Any]], path: Path) -> None:
    by_label: dict[str, tuple[list[float], list[float]]] = {}
    for run in runs:
        if "cell_c" not in run:
            continue
        label = run["degrade_label"]
        xs, ys = by_label.setdefault(label, ([], []))
        xs.extend(run["cell_c"])
        ys.extend(run["cell_growth_m"])
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for label, (xs, ys) in sorted(by_label.items()):
        ax.scatter(xs, ys, s=8, alpha=0.45, label=label)
    ax.set_xlabel("среднее c в ячейке карты")
    ax.set_ylabel("средний прирост ошибки в ячейке, м")
    ax.legend(fontsize=8)
    ax.set_title("Ячейки карты достоверности и локальный прирост ошибки")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cell-m", type=float, default=1.0)
    parser.add_argument("--min-samples", type=int, default=5)
    parser.add_argument("--horizon-s", type=float, default=1.0)
    parser.add_argument("--max-dt", type=float, default=0.1)
    args = parser.parse_args()

    runs: list[dict[str, Any]] = []
    for pair in load_batch_manifest(args.batch.resolve()):
        if pair.adaptive is None:
            continue
        res = analyze_run(
            Path(pair.adaptive.result_dir),
            cell_m=args.cell_m,
            min_samples=args.min_samples,
            horizon_s=args.horizon_s,
            max_dt=args.max_dt,
        )
        res["seq"] = pair.seq
        res["degrade"] = pair.degrade
        res["degrade_label"] = degrade_spec_to_label(pair.degrade)
        runs.append(res)
        print(f"{res['result_dir']}: r={fmt(res.get('pearson_r'))} R2={fmt(res.get('r_squared'))} "
              f"rho={fmt(res.get('spearman_r'))} cells={res.get('n_cells')} {res.get('error', '')}")

    cells: list[dict[str, Any]] = []
    for key in sorted({(r["seq"], r["degrade"]) for r in runs}):
        group = [r for r in runs if (r["seq"], r["degrade"]) == key and "pearson_r" in r]
        if not group:
            continue
        cells.append(
            {
                "seq": key[0],
                "degrade": key[1],
                "degrade_label": group[0]["degrade_label"],
                "n_runs": len(group),
                "n_cells_med": int(statistics.median(r["n_cells"] for r in group)),
                "pearson_r_med": statistics.median(r["pearson_r"] for r in group),
                "r_squared_med": statistics.median(r["r_squared"] for r in group),
                "spearman_r_med": statistics.median(r["spearman_r"] for r in group),
                "frac_p_lt_05": sum(1 for r in group if r["pearson_p"] < 0.05) / len(group),
            }
        )

    args.out.mkdir(parents=True, exist_ok=True)
    params = {
        "batch": args.batch.name,
        "cell_m": args.cell_m,
        "min_samples": args.min_samples,
        "horizon_s": args.horizon_s,
        "max_dt": args.max_dt,
    }
    slim = [{k: v for k, v in r.items() if k not in ("cell_c", "cell_growth_m")} for r in runs]
    (args.out / "map_error_link.json").write_text(
        json.dumps({"params": params, "cells": cells, "runs": slim}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_table(cells, params, args.out / "table_map_error.md")
    plot_scatter(cells, runs, args.out / "map_error_scatter.png")

    for cell in cells:
        print(f"{cell['seq']} {cell['degrade_label']}: median r={fmt(cell['pearson_r_med'])} "
              f"R2={fmt(cell['r_squared_med'])} rho={fmt(cell['spearman_r_med'])} "
              f"p<0.05 in {cell['frac_p_lt_05']:.2f}")
    print(f"artifacts: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
