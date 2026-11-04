#!/usr/bin/env python3
"""Summarize imu_vis.csv: median d, dR, flow, skip_frac; optional stale-window split."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from degrade_ros2_bag import stale_in_window  # noqa: E402


def _pctl(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    ordered = sorted(vals)
    idx = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[idx]


def summarize_imu_vis(
    path: Path,
    *,
    bag_t0: float | None = None,
    stale_w: float | None = None,
    period_s: float = 10.0,
    after_s: float = 0.0,
) -> dict[str, float | int | None]:
    d_vals: list[float] = []
    dr: list[float] = []
    flow: list[float] = []
    d_win: list[float] = []
    d_live: list[float] = []
    n_skip = 0
    n_skip_win = 0
    n_win = 0
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                d = float(row["d"])
            except (KeyError, TypeError, ValueError):
                continue
            d_vals.append(d)
            try:
                dr.append(float(row.get("dR_rad") or 0))
            except ValueError:
                pass
            try:
                flow.append(float(row.get("flow_med_px") or 0))
            except ValueError:
                pass
            try:
                skipped = int(float(row.get("skip") or 0))
            except ValueError:
                skipped = 0
            n_skip += skipped
            if bag_t0 is not None and stale_w is not None:
                try:
                    ts = float(row["timestamp"])
                except (KeyError, TypeError, ValueError):
                    continue
                if stale_in_window(ts, bag_t0, stale_w, period_s, after_s=after_s):
                    d_win.append(d)
                    n_win += 1
                    n_skip_win += skipped
                else:
                    d_live.append(d)
    n = len(d_vals)
    if n == 0:
        return {"n": 0}
    out: dict[str, float | int | None] = {
        "n": n,
        "d_mean": sum(d_vals) / n,
        "d_p50": _pctl(d_vals, 0.50),
        "dR_p50": _pctl(dr, 0.50),
        "flow_p50": _pctl(flow, 0.50),
        "skip_frac": n_skip / n,
    }
    if bag_t0 is not None and stale_w is not None:
        out["n_win"] = n_win
        out["d_win_p50"] = _pctl(d_win, 0.50)
        out["d_live_p50"] = _pctl(d_live, 0.50)
        out["skip_frac_win"] = (n_skip_win / n_win) if n_win else None
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--bag-t0", type=float, default=None, help="Bag first-image timestamp (s)")
    parser.add_argument("--stale-w", type=float, default=None, help="Freeze window W (s), period 10")
    parser.add_argument("--after", type=float, default=0.0, help="stale after T (s) from bag t0")
    args = parser.parse_args()
    for path in args.paths:
        log = path / "imu_vis.csv" if path.is_dir() else path
        if not log.is_file():
            print(f"{path}: missing {log}", file=sys.stderr)
            continue
        d = summarize_imu_vis(log, bag_t0=args.bag_t0, stale_w=args.stale_w, after_s=args.after)
        line = (
            f"{log}: n={d.get('n')}  med_d={d.get('d_p50')}  "
            f"med_dR={d.get('dR_p50')}  med_flow={d.get('flow_p50')}  skip={d.get('skip_frac')}"
        )
        if args.stale_w is not None:
            line += (
                f"  n_win={d.get('n_win')}  med_d_win={d.get('d_win_p50')}  "
                f"med_d_live={d.get('d_live_p50')}  skip_win={d.get('skip_frac_win')}"
            )
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
