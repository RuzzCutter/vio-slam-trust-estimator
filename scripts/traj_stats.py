#!/usr/bin/env python3
"""Quick trajectory health checks for demo summaries."""

from __future__ import annotations

import argparse
import math
from pathlib import Path


def load_positions(path: Path) -> list[tuple[float, float, float]]:
    pts: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        pts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return pts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("traj", type=Path)
    args = parser.parse_args()

    pts = load_positions(args.traj)
    if len(pts) < 2:
        print("poses=0 path_m=0 max_jump_m=0 diverged=1")
        return 1

    path_m = 0.0
    max_jump = 0.0
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        dz = pts[i][2] - pts[i - 1][2]
        step = math.sqrt(dx * dx + dy * dy + dz * dz)
        path_m += step
        max_jump = max(max_jump, step)

    span = math.sqrt(
        (pts[-1][0] - pts[0][0]) ** 2
        + (pts[-1][1] - pts[0][1]) ** 2
        + (pts[-1][2] - pts[0][2]) ** 2
    )
    max_coord = max(max(abs(c) for c in p) for p in pts)
    diverged = int(max_coord > 50.0 or max_jump > 5.0)

    print(f"poses={len(pts)} path_m={path_m:.2f} span_m={span:.2f} max_jump_m={max_jump:.2f} max_coord_m={max_coord:.2f} diverged={diverged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
