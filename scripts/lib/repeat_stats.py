#!/usr/bin/env python3
"""Aggregate independent batch repeats into paper statistics."""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from run_results import (
    PAIR_TTEST_MIN_N,
    AblationGroup,
    CompareRecord,
    RunRecord,
    degrade_spec_to_label,
    fmt_m,
    fmt_pct,
    load_batch_manifest,
    median_value,
)

BOOTSTRAP_B = 5000
BOOTSTRAP_SEED = 0
WILCOXON_MIN_N = PAIR_TTEST_MIN_N


@dataclass
class SampleStats:
    n: int = 0
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None

    def mean_std_label(self) -> str:
        if self.mean is None:
            return "—"
        if self.std is None:
            return fmt_m(self.mean)
        return f"{fmt_m(self.mean)}±{fmt_m(self.std)}"


@dataclass
class CompareCell:
    seq: str
    degrade: str = ""
    degrade_label: str = "clean"
    jobs: list[CompareRecord] = field(default_factory=list)

    @property
    def n_launch(self) -> int:
        return len(self.jobs)

    @property
    def success_pairs(self) -> list[CompareRecord]:
        out: list[CompareRecord] = []
        for job in self.jobs:
            b, a = job.baseline, job.adaptive
            if b is not None and a is not None and b.is_success and a.is_success:
                out.append(job)
        return out

    @property
    def n_success(self) -> int:
        return len(self.success_pairs)

    @property
    def n_fail(self) -> int:
        return self.n_launch - self.n_success

    @property
    def failure_rate(self) -> float | None:
        if self.n_launch <= 0:
            return None
        return self.n_fail / self.n_launch

    def _values(self, side: str, field: str) -> list[float]:
        vals: list[float] = []
        for job in self.jobs:
            rec = job.baseline if side == "baseline" else job.adaptive
            if rec is None or not rec.is_success:
                continue
            v = getattr(rec, field)
            if v is not None:
                vals.append(float(v))
        return vals

    def ate_stats(self, side: str) -> SampleStats:
        return sample_stats(self._values(side, "ape_rmse_m"))

    def rpe_stats(self, side: str) -> SampleStats:
        return sample_stats(self._values(side, "rpe_rmse_m"))

    def c_mean_successful(self) -> float | None:
        vals = self._values("adaptive", "c_mean")
        if not vals:
            return None
        return sum(vals) / len(vals)

    def delta_ate_pct_medians(self) -> float | None:
        base = self.ate_stats("baseline").median
        adapt = self.ate_stats("adaptive").median
        if base is None or adapt is None or base <= 0:
            return None
        return (adapt / base - 1.0) * 100.0

    def paired_values(self) -> tuple[list[float], list[float]]:
        base: list[float] = []
        adapt: list[float] = []
        for pair in self.success_pairs:
            b, a = pair.baseline, pair.adaptive
            if b is None or a is None or b.ape_rmse_m is None or a.ape_rmse_m is None:
                continue
            base.append(float(b.ape_rmse_m))
            adapt.append(float(a.ape_rmse_m))
        return base, adapt

    def paired_p(self) -> float | None:
        base, adapt = self.paired_values()
        return paired_ttest_p(base, adapt)

    def wilcoxon_p(self) -> float | None:
        base, adapt = self.paired_values()
        return wilcoxon_signed_rank_p(base, adapt)

    def bootstrap_mean_diff_ci(self) -> tuple[float, float, float] | None:
        base, adapt = self.paired_values()
        return bootstrap_mean_diff_ci(base, adapt)

    def verdict(self) -> str:
        base = self.ate_stats("baseline").median
        adapt = self.ate_stats("adaptive").median
        if base is None or adapt is None or base <= 0:
            return "no_metrics"
        ratio = adapt / base
        degraded = bool(self.degrade)
        if degraded:
            if ratio < 0.9:
                return "confirmed"
            if ratio <= 1.05:
                return "neutral"
            return "worse"
        if ratio <= 1.05:
            return "similar" if ratio >= 0.95 else "unexpected_better"
        return "worse"


def sample_stats(values: list[float]) -> SampleStats:
    if not values:
        return SampleStats()
    n = len(values)
    mean = sum(values) / n
    std = None
    if n >= 2:
        var = sum((x - mean) ** 2 for x in values) / (n - 1)
        std = math.sqrt(var)
    return SampleStats(
        n=n,
        mean=mean,
        median=median_value(values),
        std=std,
        min=min(values),
        max=max(values),
    )


def paired_ttest_p(baseline: list[float], adaptive: list[float]) -> float | None:
    if len(baseline) != len(adaptive) or len(baseline) < PAIR_TTEST_MIN_N:
        return None
    try:
        from scipy.stats import ttest_rel
    except ImportError:
        return None
    res = ttest_rel(baseline, adaptive)
    p = float(res.pvalue)
    return p if math.isfinite(p) else None


def wilcoxon_signed_rank_p(baseline: list[float], adaptive: list[float]) -> float | None:
    """Two-sided Wilcoxon signed-rank p on paired ATE (same pairs as t-test)."""
    if len(baseline) != len(adaptive) or len(baseline) < WILCOXON_MIN_N:
        return None
    diffs = [a - b for a, b in zip(adaptive, baseline)]
    if all(d == 0.0 for d in diffs):
        return None
    try:
        from scipy.stats import wilcoxon
    except ImportError:
        return None
    res = wilcoxon(baseline, adaptive, alternative="two-sided", zero_method="wilcox")
    p = float(res.pvalue)
    return p if math.isfinite(p) else None


def bootstrap_mean_diff_ci(
    baseline: list[float],
    adaptive: list[float],
    *,
    n_boot: int = BOOTSTRAP_B,
    alpha: float = 0.05,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float, float] | None:
    """Percentile 95% CI for mean(ATE_adapt − ATE_base) by resampling pairs."""
    if len(baseline) != len(adaptive) or len(baseline) < WILCOXON_MIN_N:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    diffs = np.asarray(adaptive, dtype=float) - np.asarray(baseline, dtype=float)
    n = diffs.size
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = diffs[idx].mean(axis=1)
    lo = float(np.percentile(means, 100.0 * alpha / 2.0))
    hi = float(np.percentile(means, 100.0 * (1.0 - alpha / 2.0)))
    return lo, hi, float(diffs.mean())


def fmt_ci(ci: tuple[float, float, float] | None) -> str:
    if ci is None:
        return "—"
    lo, hi, _ = ci
    return f"[{fmt_m(lo)}, {fmt_m(hi)}]"


def ci_contains_zero(ci: tuple[float, float, float] | None) -> bool | None:
    if ci is None:
        return None
    lo, hi, _ = ci
    return lo <= 0.0 <= hi


def aggregate_compare(rows: list[CompareRecord]) -> list[CompareCell]:
    groups: dict[tuple[str, str], CompareCell] = {}
    for row in rows:
        key = (row.seq, row.degrade)
        if key not in groups:
            groups[key] = CompareCell(
                seq=row.seq,
                degrade=row.degrade,
                degrade_label=row.degrade_label or degrade_spec_to_label(row.degrade),
            )
        groups[key].jobs.append(row)
    return sorted(groups.values(), key=lambda c: (c.seq, c.degrade))


def fmt_p(value: float | None) -> str:
    if value is None:
        return "—"
    if value < 1e-4:
        return "<1e-4"
    return f"{value:.3g}"


def fmt_fail(cell: CompareCell) -> str:
    if cell.n_launch <= 0:
        return "—"
    return f"{cell.n_fail}/{cell.n_launch}"


VERDICT_RU = {
    "confirmed": "подтверждена",
    "neutral": "нейтрально",
    "similar": "≈ baseline",
    "unexpected_better": "лучше на clean",
    "worse": "хуже",
    "no_metrics": "нет метрик",
}


def render_repeats_markdown(cells: list[CompareCell], *, title: str = "") -> str:
    lines: list[str] = []
    if title:
        lines.extend([f"## {title}", ""])
    lines.append(
        "| Seq | Условие | n | ATE base | ATE adapt | ΔATE med | p_t | p_W | "
        "ΔATE CI | RPE base | RPE adapt | c̄ | Failure | Вердикт |"
    )
    lines.append(
        "|-----|---------|---|----------|-----------|----------|-----|-----|"
        "---------|----------|-----------|-----|---------|---------|"
    )
    for cell in cells:
        b = cell.ate_stats("baseline")
        a = cell.ate_stats("adaptive")
        rb = cell.rpe_stats("baseline")
        ra = cell.rpe_stats("adaptive")
        lines.append(
            "| {seq} | {cond} | {n} | {bate} | {aate} | {d} | {p} | {w} | {ci} | {brpe} | {arpe} | {c} | {fail} | {v} |".format(
                seq=cell.seq,
                cond=cell.degrade_label,
                n=f"{cell.n_success}/{cell.n_launch}",
                bate=b.mean_std_label(),
                aate=a.mean_std_label(),
                d=fmt_pct(cell.delta_ate_pct_medians()),
                p=fmt_p(cell.paired_p()),
                w=fmt_p(cell.wilcoxon_p()),
                ci=fmt_ci(cell.bootstrap_mean_diff_ci()),
                brpe=rb.mean_std_label(),
                arpe=ra.mean_std_label(),
                c=fmt_m(cell.c_mean_successful()),
                fail=fmt_fail(cell),
                v=VERDICT_RU.get(cell.verdict(), cell.verdict()),
            )
        )
    lines.append("")
    lines.append(
        "ATE/RPE: mean±std (sample, ddof=1) по успешным прогонам. "
        "ΔATE — по медианам. p_t — парный t-тест, p_W — Вилкоксон signed-rank "
        f"(n_пар ≥ {PAIR_TTEST_MIN_N}), иначе «—». "
        "ΔATE CI — бутстрап 95 % ДИ mean(ATE_adapt − ATE_base), B=5000. "
        "Если 0 внутри ДИ — не писать «значимо снижает». "
        "Failure = n_fail/n_launch."
    )
    lines.append("")
    return "\n".join(lines)


def render_repeats_latex(cells: list[CompareCell], *, caption: str = "", label: str = "tab:ate_repeats") -> str:
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{llcccccccc}",
        "\\hline",
        "Seq & Cond. & n & ATE$_b$ & ATE$_a$ & $\\Delta$ATE & $p_t$ & $p_W$ & CI & Fail \\\\",
        "\\hline",
    ]
    for cell in cells:
        b = cell.ate_stats("baseline")
        a = cell.ate_stats("adaptive")
        lines.append(
            f"{cell.seq.replace('_', '\\_')} & {cell.degrade_label} & "
            f"{cell.n_success}/{cell.n_launch} & {b.mean_std_label()} & {a.mean_std_label()} & "
            f"{fmt_pct(cell.delta_ate_pct_medians())} & {fmt_p(cell.paired_p())} & "
            f"{fmt_p(cell.wilcoxon_p())} & {fmt_ci(cell.bootstrap_mean_diff_ci())} & "
            f"{fmt_fail(cell)} \\\\"
        )
    lines.extend(["\\hline", "\\end{tabular}"])
    if caption:
        lines.append(f"\\caption{{{caption}}}")
    lines.append(f"\\label{{{label}}}")
    lines.append("\\end{table}")
    lines.append("")
    return "\n".join(lines)


def render_repeats_csv(cells: list[CompareCell]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "seq", "degrade", "degrade_label",
        "n_launch", "n_fail", "n_success", "failure_rate",
        "ate_base_mean", "ate_base_std", "ate_base_median", "ate_base_min", "ate_base_max",
        "ate_adapt_mean", "ate_adapt_std", "ate_adapt_median", "ate_adapt_min", "ate_adapt_max",
        "delta_ate_pct_median", "p_paired", "p_wilcoxon",
        "delta_mean_ci_lo", "delta_mean_ci_hi", "delta_mean",
        "rpe_base_mean", "rpe_base_std", "rpe_base_median",
        "rpe_adapt_mean", "rpe_adapt_std", "rpe_adapt_median",
        "c_mean", "verdict",
    ])
    for cell in cells:
        b = cell.ate_stats("baseline")
        a = cell.ate_stats("adaptive")
        rb = cell.rpe_stats("baseline")
        ra = cell.rpe_stats("adaptive")
        ci = cell.bootstrap_mean_diff_ci()
        writer.writerow([
            cell.seq, cell.degrade, cell.degrade_label,
            cell.n_launch, cell.n_fail, cell.n_success,
            cell.failure_rate if cell.failure_rate is not None else "",
            b.mean, b.std, b.median, b.min, b.max,
            a.mean, a.std, a.median, a.min, a.max,
            cell.delta_ate_pct_medians() if cell.delta_ate_pct_medians() is not None else "",
            cell.paired_p() if cell.paired_p() is not None else "",
            cell.wilcoxon_p() if cell.wilcoxon_p() is not None else "",
            ci[0] if ci is not None else "",
            ci[1] if ci is not None else "",
            ci[2] if ci is not None else "",
            rb.mean, rb.std, rb.median,
            ra.mean, ra.std, ra.median,
            cell.c_mean_successful() if cell.c_mean_successful() is not None else "",
            cell.verdict(),
        ])
    return out.getvalue()


def successful_adaptive_from_compare(rows: list[CompareRecord], seq: str, degrade: str) -> list[RunRecord]:
    out: list[RunRecord] = []
    for row in rows:
        if row.seq != seq or (row.degrade or "") != (degrade or ""):
            continue
        if row.adaptive is not None and row.adaptive.is_success:
            out.append(row.adaptive)
    return out


def attach_compare_full(
    groups: list[AblationGroup],
    compare_rows: list[CompareRecord],
) -> list[AblationGroup]:
    """Replace ablation 'full' with successful adaptive runs from the compare series."""
    for group in groups:
        full_runs = successful_adaptive_from_compare(compare_rows, group.seq, group.degrade)
        if not full_runs:
            continue
        group.variants["full"] = full_runs
        group.full_source = "compare"
    return groups


def attach_compare_full_from_batch(groups: list[AblationGroup], compare_batch: Path) -> list[AblationGroup]:
    return attach_compare_full(groups, load_batch_manifest(compare_batch))


def pick_map_runs(runs: list[RunRecord]) -> tuple[RunRecord | None, RunRecord | None]:
    """Median-ATE successful run and worst successful run (for paper figures)."""
    ok = [r for r in runs if r.is_success and r.ape_rmse_m is not None]
    if not ok:
        return None, None
    ordered = sorted(ok, key=lambda r: float(r.ape_rmse_m))  # type: ignore[arg-type]
    median_run = ordered[len(ordered) // 2]
    return median_run, ordered[-1]


def cell_to_dict(cell: CompareCell) -> dict[str, Any]:
    b = cell.ate_stats("baseline")
    a = cell.ate_stats("adaptive")
    return {
        "seq": cell.seq,
        "degrade": cell.degrade,
        "n_launch": cell.n_launch,
        "n_fail": cell.n_fail,
        "n_success": cell.n_success,
        "ate_base_median": b.median,
        "ate_adapt_median": a.median,
        "delta_ate_pct_median": cell.delta_ate_pct_medians(),
        "p_paired": cell.paired_p(),
        "p_wilcoxon": cell.wilcoxon_p(),
        "delta_mean_ci": cell.bootstrap_mean_diff_ci(),
        "c_mean": cell.c_mean_successful(),
        "verdict": cell.verdict(),
    }
