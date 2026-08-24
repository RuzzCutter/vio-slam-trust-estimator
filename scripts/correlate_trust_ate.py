#!/usr/bin/env python3
"""Correlate per-pose ATE with trust c(t) after Sim(3) alignment.

Examples:
  python3 scripts/correlate_trust_ate.py --batch datasets/results/batches/paper_main_...
  python3 scripts/correlate_trust_ate.py --result-dir datasets/results/MH_04_difficult_adaptive_...
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from build_trust_map import load_trust_log  # noqa: E402
from repeat_stats import pick_map_runs  # noqa: E402
from run_results import (  # noqa: E402
    CompareRecord,
    RunRecord,
    degrade_spec_to_label,
    fmt_m,
    load_batch_manifest,
    load_run_record,
)

DEFAULT_C_SKIP = 0.15
DEFAULT_WINDOW_S = 2.0
DEFAULT_MAX_DT = 0.1


@dataclass
class RunCorr:
    result_dir: str
    seq: str
    degrade: str
    n_aligned: int = 0
    pearson_r: float | None = None
    pearson_p: float | None = None
    spearman_r: float | None = None
    spearman_p: float | None = None
    pearson_r_window: float | None = None
    spearman_r_window: float | None = None
    c_p10: float | None = None
    c_p50: float | None = None
    c_p90: float | None = None
    skip_frac: float | None = None
    c_mean: float | None = None
    ape_rmse_m: float | None = None
    window_s: float = DEFAULT_WINDOW_S
    c_skip: float = DEFAULT_C_SKIP
    align_method: str = ""
    error: str = ""


@dataclass
class CellCorr:
    seq: str
    degrade: str
    degrade_label: str
    runs: list[RunCorr] = field(default_factory=list)

    def _ok(self) -> list[RunCorr]:
        return [r for r in self.runs if r.pearson_r is not None]

    def median_pearson(self) -> float | None:
        vals = [r.pearson_r for r in self._ok() if r.pearson_r is not None]
        return float(np.median(vals)) if vals else None

    def pearson_range(self) -> tuple[float | None, float | None]:
        vals = [r.pearson_r for r in self._ok() if r.pearson_r is not None]
        if not vals:
            return None, None
        return float(min(vals)), float(max(vals))

    def frac_p_lt_05(self) -> float | None:
        ok = self._ok()
        if not ok:
            return None
        n = sum(1 for r in ok if r.pearson_p is not None and r.pearson_p < 0.05)
        return n / len(ok)


def load_pose_errors(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "t" not in df.columns or "e_ate_m" not in df.columns:
        raise ValueError(f"pose_errors must contain t,e_ate_m: {path}")
    return df.sort_values("t").reset_index(drop=True)


def _corr(x: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None, float | None, float | None]:
    if x.size < 5 or y.size < 5:
        return None, None, None, None
    if np.allclose(x, x[0]) or np.allclose(y, y[0]):
        return None, None, None, None
    try:
        from scipy.stats import pearsonr, spearmanr
    except ImportError:
        pr = float(np.corrcoef(x, y)[0, 1])
        return (pr if math.isfinite(pr) else None), None, None, None
    pr, pp = pearsonr(x, y)
    sr, sp = spearmanr(x, y)
    pr_f = float(pr) if math.isfinite(float(pr)) else None
    sr_f = float(sr) if math.isfinite(float(sr)) else None
    return pr_f, float(pp), sr_f, float(sp)


def rolling_means(t: np.ndarray, c: np.ndarray, e: np.ndarray, window_s: float) -> tuple[np.ndarray, np.ndarray]:
    half = window_s / 2.0
    c_w = np.empty_like(c)
    e_w = np.empty_like(e)
    j0 = 0
    n = t.size
    for i in range(n):
        lo, hi = t[i] - half, t[i] + half
        while j0 < n and t[j0] < lo:
            j0 += 1
        j1 = i
        while j1 < n and t[j1] <= hi:
            j1 += 1
        sl = slice(j0, j1)
        c_w[i] = float(c[sl].mean()) if j1 > j0 else c[i]
        e_w[i] = float(e[sl].mean()) if j1 > j0 else e[i]
    return c_w, e_w


def align_c_and_e(
    trust: pd.DataFrame,
    errors: pd.DataFrame,
    *,
    max_dt: float,
) -> tuple[pd.DataFrame, str]:
    merged = pd.merge_asof(
        trust.sort_values("t"),
        errors.sort_values("t"),
        on="t",
        direction="nearest",
        tolerance=max_dt,
    )
    merged = merged.dropna(subset=["c", "e_ate_m"])
    if len(merged) >= max(1, int(0.5 * len(trust))):
        return merged, "timestamp"
    # index fallback
    n = min(len(trust), len(errors))
    if n < 5:
        return merged, "timestamp"
    out = pd.DataFrame({
        "t": trust["t"].to_numpy()[:n],
        "c": trust["c"].to_numpy()[:n],
        "e_ate_m": errors["e_ate_m"].to_numpy()[:n],
    })
    return out, "index"


def correlate_run(
    result_dir: Path,
    *,
    window_s: float,
    c_skip: float,
    max_dt: float,
) -> RunCorr:
    rec = load_run_record(result_dir)
    out = RunCorr(
        result_dir=str(result_dir.resolve()),
        seq=rec.seq,
        degrade=rec.degrade,
        ape_rmse_m=rec.ape_rmse_m,
        window_s=window_s,
        c_skip=c_skip,
        c_mean=rec.c_mean,
    )
    trust_path = result_dir / "trust_log.csv"
    err_path = result_dir / "metrics" / "pose_errors.csv"
    if not trust_path.is_file():
        out.error = "no trust_log.csv"
        return out
    trust = load_trust_log(trust_path)
    c = trust["c"].to_numpy(dtype=float)
    out.c_p10 = float(np.nanquantile(c, 0.10))
    out.c_p50 = float(np.nanquantile(c, 0.50))
    out.c_p90 = float(np.nanquantile(c, 0.90))
    out.skip_frac = float(np.mean(c < c_skip)) if c.size else None
    if rec.c_mean is None and c.size:
        out.c_mean = float(np.nanmean(c))

    if not err_path.is_file():
        out.error = "no pose_errors.csv"
        return out
    errors = load_pose_errors(err_path)
    aligned, method = align_c_and_e(trust, errors, max_dt=max_dt)
    out.align_method = method
    out.n_aligned = int(len(aligned))
    if out.n_aligned < 5:
        out.error = "too few aligned samples"
        return out
    x = aligned["c"].to_numpy(dtype=float)
    y = aligned["e_ate_m"].to_numpy(dtype=float)
    out.pearson_r, out.pearson_p, out.spearman_r, out.spearman_p = _corr(x, y)
    c_w, e_w = rolling_means(aligned["t"].to_numpy(dtype=float), x, y, window_s)
    wr, _, ws, _ = _corr(c_w, e_w)
    out.pearson_r_window = wr
    out.spearman_r_window = ws
    return out


def write_run_meta(corr: RunCorr, result_dir: Path) -> None:
    meta = {
        "window_s": corr.window_s,
        "c_skip": corr.c_skip,
        "align_method": corr.align_method,
        "n_aligned": corr.n_aligned,
        "pearson_r": corr.pearson_r,
        "pearson_p": corr.pearson_p,
        "spearman_r": corr.spearman_r,
        "spearman_p": corr.spearman_p,
        "pearson_r_window": corr.pearson_r_window,
        "spearman_r_window": corr.spearman_r_window,
        "c_p10": corr.c_p10,
        "c_p50": corr.c_p50,
        "c_p90": corr.c_p90,
        "skip_frac": corr.skip_frac,
    }
    path = result_dir / "trust_corr.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def group_cells(corrs: list[RunCorr]) -> list[CellCorr]:
    groups: dict[tuple[str, str], CellCorr] = {}
    for corr in corrs:
        key = (corr.seq, corr.degrade)
        if key not in groups:
            groups[key] = CellCorr(
                seq=corr.seq,
                degrade=corr.degrade,
                degrade_label=degrade_spec_to_label(corr.degrade),
            )
        groups[key].runs.append(corr)
    return sorted(groups.values(), key=lambda c: (c.seq, c.degrade))


def render_corr_markdown(cells: list[CellCorr], *, title: str) -> str:
    lines = [
        f"## {title}",
        "",
        "| Seq | Условие | n | median r (Pearson) | min…max r | доля p<0.05 | median Spearman | c p10/p50/p90 | skip |",
        "|-----|---------|---|-------------------|-----------|-------------|-----------------|---------------|------|",
    ]
    for cell in cells:
        ok = cell._ok()
        sp = [r.spearman_r for r in ok if r.spearman_r is not None]
        p10 = [r.c_p10 for r in cell.runs if r.c_p10 is not None]
        p50 = [r.c_p50 for r in cell.runs if r.c_p50 is not None]
        p90 = [r.c_p90 for r in cell.runs if r.c_p90 is not None]
        skip = [r.skip_frac for r in cell.runs if r.skip_frac is not None]
        rmin, rmax = cell.pearson_range()
        q = "—"
        if p10 and p50 and p90:
            q = f"{float(np.median(p10)):.3f}/{float(np.median(p50)):.3f}/{float(np.median(p90)):.3f}"
        lines.append(
            "| {seq} | {cond} | {n} | {r} | {rng} | {fp} | {s} | {q} | {sk} |".format(
                seq=cell.seq,
                cond=cell.degrade_label,
                n=len(ok),
                r=fmt_m(cell.median_pearson(), 3),
                rng=f"{fmt_m(rmin, 3)}…{fmt_m(rmax, 3)}" if rmin is not None else "—",
                fp=fmt_m(cell.frac_p_lt_05(), 2) if cell.frac_p_lt_05() is not None else "—",
                s=fmt_m(float(np.median(sp)), 3) if sp else "—",
                q=q,
                sk=fmt_m(float(np.median(skip)), 3) if skip else "—",
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_corr_csv(cells: list[CellCorr]) -> str:
    import io

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "seq", "degrade", "n_runs", "median_pearson_r", "min_pearson_r", "max_pearson_r",
        "frac_p_lt_0.05", "median_spearman_r", "c_p10", "c_p50", "c_p90", "skip_frac",
    ])
    for cell in cells:
        ok = cell._ok()
        rmin, rmax = cell.pearson_range()
        sp = [r.spearman_r for r in ok if r.spearman_r is not None]
        p10 = [r.c_p10 for r in cell.runs if r.c_p10 is not None]
        p50 = [r.c_p50 for r in cell.runs if r.c_p50 is not None]
        p90 = [r.c_p90 for r in cell.runs if r.c_p90 is not None]
        skip = [r.skip_frac for r in cell.runs if r.skip_frac is not None]
        writer.writerow([
            cell.seq, cell.degrade, len(ok),
            cell.median_pearson() if cell.median_pearson() is not None else "",
            rmin if rmin is not None else "",
            rmax if rmax is not None else "",
            cell.frac_p_lt_05() if cell.frac_p_lt_05() is not None else "",
            float(np.median(sp)) if sp else "",
            float(np.median(p10)) if p10 else "",
            float(np.median(p50)) if p50 else "",
            float(np.median(p90)) if p90 else "",
            float(np.median(skip)) if skip else "",
        ])
    return out.getvalue()


def adaptive_dirs_from_batch(rows: list[CompareRecord]) -> list[Path]:
    dirs: list[Path] = []
    for row in rows:
        if row.adaptive and row.adaptive.result_dir:
            dirs.append(Path(row.adaptive.result_dir))
    return dirs


def main() -> int:
    parser = argparse.ArgumentParser(description="Correlate c(t) with per-pose ATE")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--batch", type=Path, help="Compare batch with manifest.jsonl")
    src.add_argument("--result-dir", type=Path, help="Single adaptive RESULT_DIR")
    src.add_argument("--scan", type=Path, help="Scan results root for adaptive dirs")
    parser.add_argument("--out", type=Path, default=ROOT / "paper_tables")
    parser.add_argument("--window-s", type=float, default=DEFAULT_WINDOW_S)
    parser.add_argument("--c-skip", type=float, default=DEFAULT_C_SKIP)
    parser.add_argument("--max-dt", type=float, default=DEFAULT_MAX_DT)
    args = parser.parse_args()

    result_dirs: list[Path] = []
    source = ""
    compare_rows: list[CompareRecord] = []
    if args.batch:
        compare_rows = load_batch_manifest(args.batch.resolve())
        result_dirs = adaptive_dirs_from_batch(compare_rows)
        source = args.batch.name
    elif args.result_dir:
        result_dirs = [args.result_dir.resolve()]
        source = args.result_dir.name
    else:
        root = args.scan.resolve()
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "trust_log.csv").is_file() and "adaptive" in child.name:
                result_dirs.append(child)
        source = root.name

    if not result_dirs:
        print("No adaptive result dirs found.", file=sys.stderr)
        return 1

    corrs: list[RunCorr] = []
    for rd in result_dirs:
        corr = correlate_run(rd, window_s=args.window_s, c_skip=args.c_skip, max_dt=args.max_dt)
        write_run_meta(corr, rd)
        corrs.append(corr)
        status = "ok" if corr.pearson_r is not None else corr.error or "no r"
        print(f"{rd.name}: r={corr.pearson_r} p={corr.pearson_p} skip={corr.skip_frac} ({status})")

    cells = group_cells(corrs)
    args.out.mkdir(parents=True, exist_ok=True)
    md = args.out / "table_trust_corr.md"
    md.write_text(render_corr_markdown(cells, title=f"c(t) vs e(t) ({source})"), encoding="utf-8")
    csv_path = args.out / "table_trust_corr.csv"
    csv_path.write_text(render_corr_csv(cells), encoding="utf-8")
    summary = {
        "window_s": args.window_s,
        "c_skip": args.c_skip,
        "max_dt": args.max_dt,
        "source": source,
        "n_runs": len(corrs),
        "cells": [
            {
                "seq": c.seq,
                "degrade": c.degrade,
                "median_pearson_r": c.median_pearson(),
                "frac_p_lt_0.05": c.frac_p_lt_05(),
            }
            for c in cells
        ],
    }
    (args.out / "trust_corr_meta.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {md}")
    print(f"Wrote {csv_path}")

    if compare_rows:
        by_cell: dict[tuple[str, str], list[RunRecord]] = {}
        for row in compare_rows:
            if row.adaptive is None:
                continue
            by_cell.setdefault((row.seq, row.degrade), []).append(row.adaptive)
        print("Map runs (median ATE / worst successful):")
        for (seq, degrade), runs in sorted(by_cell.items()):
            med, worst = pick_map_runs(runs)
            label = degrade_spec_to_label(degrade)
            if med:
                print(f"  {seq} {label}: median {med.result_dir}")
            if worst:
                print(f"  {seq} {label}: worst  {worst.result_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
