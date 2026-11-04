#!/usr/bin/env python3
"""Summarize trust_log.csv: c̄, p10(c), skip_frac, mean n_features, mean noise_scale."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path


def _pctl(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    ordered = sorted(vals)
    idx = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[idx]


def summarize_trust_log(path: Path) -> dict[str, float | int | None]:
    c_vals: list[float] = []
    n_feat: list[float] = []
    scales: list[float] = []
    n_skip = 0
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                c_vals.append(float(row["c"]))
            except (KeyError, TypeError, ValueError):
                continue
            try:
                n_feat.append(float(row.get("n_features") or 0))
            except ValueError:
                pass
            try:
                scales.append(float(row.get("noise_scale") or 0))
            except ValueError:
                pass
            try:
                n_skip += int(float(row.get("skip_update") or 0))
            except ValueError:
                pass
    n = len(c_vals)
    if n == 0:
        return {"n": 0}
    mean_c = sum(c_vals) / n
    var = sum((x - mean_c) ** 2 for x in c_vals) / max(1, n - 1)
    return {
        "n": n,
        "c_mean": mean_c,
        "c_std": math.sqrt(var) if n > 1 else 0.0,
        "c_p10": _pctl(c_vals, 0.10),
        "c_p50": _pctl(c_vals, 0.50),
        "skip_frac": n_skip / n,
        "n_features_mean": (sum(n_feat) / len(n_feat)) if n_feat else None,
        "noise_scale_mean": (sum(scales) / len(scales)) if scales else None,
        "noise_scale_p50": _pctl(scales, 0.50) if scales else None,
        "noise_scale_min": min(scales) if scales else None,
        "noise_scale_max": max(scales) if scales else None,
    }


def fmt_row(d: dict[str, float | int | None]) -> str:
    def f(key: str, digits: int = 3) -> str:
        v = d.get(key)
        if v is None:
            return "—"
        if isinstance(v, int):
            return str(v)
        return f"{v:.{digits}f}"

    return (
        f"n={f('n', 0)}  c̄={f('c_mean')}  med_c={f('c_p50')}  p10={f('c_p10')}  "
        f"skip={f('skip_frac')}  n_feat={f('n_features_mean', 1)}  "
        f"s̄={f('noise_scale_mean')}  med_s={f('noise_scale_p50')} "
        f"[{f('noise_scale_min')}, {f('noise_scale_max')}]"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize trust_log.csv")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.paths:
        log = path / "trust_log.csv" if path.is_dir() else path
        if not log.is_file():
            print(f"{path}: missing {log}", file=sys.stderr)
            continue
        print(f"{log}: {fmt_row(summarize_trust_log(log))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
