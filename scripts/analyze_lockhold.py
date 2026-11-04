#!/usr/bin/env python3
"""Lock-hold stand summary: valid runs, failures and ATE under the stale-frame fault.

A run counts only if the filter initialised before the fault starts and produced
poses after it (init failure is a property of the stand, not of the compared modes).
A run is a failure if the trajectory diverged, ATE >= --ate-abs, or ATE >= --ate-ratio
times the median baseline ATE on clean data of the same batch.

Examples:
  python3 scripts/analyze_lockhold.py
  python3 scripts/analyze_lockhold.py --batch datasets/results/batches/v11_f_20260910_220012
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from run_results import RunRecord, load_batch_manifest  # noqa: E402
from summarize_imu_vis import summarize_imu_vis  # noqa: E402

BATCHES = ROOT / "datasets" / "results" / "batches"
DEFAULT_OUT = ROOT / "paper_tables" / "v11_lockhold"
DEFAULT_BATCHES = [
    BATCHES / "v11_g2_20260910_213625",
    BATCHES / "v11_f_20260910_220012",
]

DEFAULT_BAG_T0 = 1403638127.3298728
DEFAULT_LIE_START = 30.0
DEFAULT_W = 4.0
DEFAULT_PERIOD = 10.0


def trajectory_bounds(result_dir: Path, bag_t0: float, lie_start: float) -> tuple[float | None, int, int]:
    """Return (first pose time relative to bag t0, total poses, poses after the fault start)."""
    traj = result_dir / "trajectory_tum.txt"
    if not traj.is_file():
        return None, 0, 0
    times: list[float] = []
    for line in traj.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            times.append(float(line.split()[0]))
        except (IndexError, ValueError):
            continue
    if not times:
        return None, 0, 0
    after = sum(1 for t in times if t >= bag_t0 + lie_start)
    return times[0] - bag_t0, len(times), after


def run_side(rec: RunRecord | None, *, bag_t0: float, lie_start: float) -> dict[str, Any]:
    if rec is None:
        return {"result_dir": None, "valid": False, "ate_m": None, "diverged": None}
    path = Path(rec.result_dir)
    first_rel, poses, poses_after = trajectory_bounds(path, bag_t0, lie_start)
    valid = first_rel is not None and first_rel < lie_start and poses_after > 0
    return {
        "result_dir": path.name,
        "valid": bool(valid),
        "init_rel_s": first_rel,
        "poses": poses,
        "poses_after_fault": poses_after,
        "ate_m": rec.ape_rmse_m,
        "diverged": bool(rec.diverged),
        "max_coord_m": rec.max_coord_m,
    }


def skip_fractions(result_dir: str | None, *, bag_t0: float, w: float, period: float, after: float) -> dict[str, float | None]:
    if not result_dir:
        return {"skip_frac": None, "skip_frac_win": None}
    log = Path(result_dir) / "imu_vis.csv"
    if not log.is_file():
        return {"skip_frac": None, "skip_frac_win": None}
    stats = summarize_imu_vis(log, bag_t0=bag_t0, stale_w=w, period_s=period, after_s=after)
    return {"skip_frac": stats.get("skip_frac"), "skip_frac_win": stats.get("skip_frac_win")}


def is_failure(side: dict[str, Any], poison_ate: float) -> bool:
    if not side["valid"]:
        return False
    if side.get("diverged"):
        return True
    ate = side.get("ate_m")
    return ate is not None and ate >= poison_ate


def median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def analyze_batch(
    batch: Path,
    *,
    bag_t0: float,
    lie_start: float,
    w: float,
    period: float,
    ate_abs: float,
    ate_ratio: float,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for pair in load_batch_manifest(batch):
        base = run_side(pair.baseline, bag_t0=bag_t0, lie_start=lie_start)
        adapt = run_side(pair.adaptive, bag_t0=bag_t0, lie_start=lie_start)
        adaptive_dir = pair.adaptive.result_dir if pair.adaptive else None
        adapt.update(skip_fractions(adaptive_dir, bag_t0=bag_t0, w=w, period=period, after=lie_start))
        runs.append({"repeat": pair.repeat, "degrade": pair.degrade, "baseline": base, "adaptive": adapt})

    clean_base = [r["baseline"]["ate_m"] for r in runs if not r["degrade"] and r["baseline"]["ate_m"] is not None]
    med_clean = median_or_none(clean_base)
    poison_ate = min(ate_abs, ate_ratio * med_clean) if med_clean else ate_abs

    cells: list[dict[str, Any]] = []
    for degrade in sorted({r["degrade"] for r in runs}):
        cell_runs = [r for r in runs if r["degrade"] == degrade]
        base_ate = [r["baseline"]["ate_m"] for r in cell_runs if r["baseline"]["valid"] and r["baseline"]["ate_m"] is not None]
        adapt_ate = [r["adaptive"]["ate_m"] for r in cell_runs if r["adaptive"]["valid"] and r["adaptive"]["ate_m"] is not None]
        skips = [r["adaptive"]["skip_frac"] for r in cell_runs if r["adaptive"].get("skip_frac") is not None]
        skips_win = [r["adaptive"]["skip_frac_win"] for r in cell_runs if r["adaptive"].get("skip_frac_win") is not None]
        cells.append(
            {
                "degrade": degrade or "clean",
                "n": len(cell_runs),
                "n_valid_base": sum(1 for r in cell_runs if r["baseline"]["valid"]),
                "n_valid_adapt": sum(1 for r in cell_runs if r["adaptive"]["valid"]),
                "failures_base": sum(1 for r in cell_runs if is_failure(r["baseline"], poison_ate)),
                "failures_adapt": sum(1 for r in cell_runs if is_failure(r["adaptive"], poison_ate)),
                "n_ate_base": len(base_ate),
                "n_ate_adapt": len(adapt_ate),
                "ate_med_base": median_or_none(base_ate),
                "ate_med_adapt": median_or_none(adapt_ate),
                "skip_frac_med": median_or_none(skips),
                "skip_frac_win_med": median_or_none(skips_win),
            }
        )
    return {
        "batch": batch.name,
        "n_pairs": len(runs),
        "clean_median_baseline_ate_m": med_clean,
        "poison_ate_m": poison_ate,
        "cells": cells,
        "runs": runs,
    }


def fmt(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def write_table(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "## Стенд удержания лока: устаревший кадр после инициализации",
        "",
        "Отказом считается расхождение траектории либо ATE не ниже порога яда "
        "(2 м или тройная медиана ATE базового режима на чистых данных — что меньше). "
        "Прогоны с инициализацией позже начала отказа в сравнение не входят.",
        "",
    ]
    for res in results:
        lines += [
            f"### {res['batch']}",
            "",
            f"Пар прогонов: {res['n_pairs']}; медиана ATE базового режима на чистых данных "
            f"{fmt(res['clean_median_baseline_ate_m'])} м; порог яда {fmt(res['poison_ate_m'])} м.",
            "",
            "| Условие | Валидных пар | Отказы базовый | Отказы адаптивный | Медиана ATE базовый, м | Медиана ATE адаптивный, м | Доля пропусков | Доля пропусков в окнах |",
            "|---------|--------------|----------------|-------------------|------------------------|---------------------------|----------------|------------------------|",
        ]
        for cell in res["cells"]:
            lines.append(
                f"| {cell['degrade']} | {min(cell['n_valid_base'], cell['n_valid_adapt'])}/{cell['n']} "
                f"| {cell['failures_base']}/{cell['n']} | {cell['failures_adapt']}/{cell['n']} "
                f"| {fmt(cell['ate_med_base'])} (n={cell['n_ate_base']}) "
                f"| {fmt(cell['ate_med_adapt'])} (n={cell['n_ate_adapt']}) "
                f"| {fmt(cell['skip_frac_med'], 4)} | {fmt(cell['skip_frac_win_med'], 3)} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", nargs="*", type=Path, default=DEFAULT_BATCHES)
    parser.add_argument("--bag-t0", type=float, default=DEFAULT_BAG_T0)
    parser.add_argument("--lie-start", type=float, default=DEFAULT_LIE_START, help="Fault start T, s from first image")
    parser.add_argument("--stale-w", type=float, default=DEFAULT_W)
    parser.add_argument("--period", type=float, default=DEFAULT_PERIOD)
    parser.add_argument("--ate-abs", type=float, default=2.0)
    parser.add_argument("--ate-ratio", type=float, default=3.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    results = [
        analyze_batch(
            batch if batch.is_absolute() or batch.exists() else BATCHES / batch.name,
            bag_t0=args.bag_t0,
            lie_start=args.lie_start,
            w=args.stale_w,
            period=args.period,
            ate_abs=args.ate_abs,
            ate_ratio=args.ate_ratio,
        )
        for batch in args.batch
    ]

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_table(results, args.out / "table_lockhold.md")

    for res in results:
        print(f"{res['batch']}: poison ATE >= {fmt(res['poison_ate_m'])} m")
        for cell in res["cells"]:
            print(
                f"  {cell['degrade']:>18}  failures {cell['failures_base']}/{cell['n']} -> {cell['failures_adapt']}/{cell['n']}"
                f"  med ATE {fmt(cell['ate_med_base'])} -> {fmt(cell['ate_med_adapt'])}"
                f"  skip {fmt(cell['skip_frac_med'], 4)} / win {fmt(cell['skip_frac_win_med'], 3)}"
            )
    print(f"artifacts: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
