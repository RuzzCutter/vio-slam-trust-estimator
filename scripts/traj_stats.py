#!/usr/bin/env python3
"""Quick trajectory health checks for demo summaries."""

from __future__ import annotations

import argparse
import math
from pathlib import Path


def load_poses(path: Path) -> list[tuple[float, float, float, float]]:
    """Return (t, x, y, z) rows from a TUM trajectory."""
    pts: list[tuple[float, float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        t = float(parts[0]) if len(parts) >= 8 or _looks_like_time(parts[0]) else float(len(pts))
        pts.append((t, float(parts[1]), float(parts[2]), float(parts[3])))
    return pts


def _looks_like_time(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False


def load_positions(path: Path) -> list[tuple[float, float, float]]:
    return [(p[1], p[2], p[3]) for p in load_poses(path)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("traj", type=Path)
    args = parser.parse_args()

    poses = load_poses(args.traj)
    if len(poses) < 2:
        print("poses=0 path_m=0 max_jump_m=0 max_gap_s=0 max_coord_m=0 diverged=1")
        return 1

    path_m = 0.0
    max_jump = 0.0
    max_gap = 0.0
    for i in range(1, len(poses)):
        dx = poses[i][1] - poses[i - 1][1]
        dy = poses[i][2] - poses[i - 1][2]
        dz = poses[i][3] - poses[i - 1][3]
        step = math.sqrt(dx * dx + dy * dy + dz * dz)
        path_m += step
        max_jump = max(max_jump, step)
        max_gap = max(max_gap, poses[i][0] - poses[i - 1][0])

    span = math.sqrt(
        (poses[-1][1] - poses[0][1]) ** 2
        + (poses[-1][2] - poses[0][2]) ** 2
        + (poses[-1][3] - poses[0][3]) ** 2
    )
    max_coord = max(max(abs(c) for c in p[1:]) for p in poses)
    # Indoor EuRoC stays well under this; KITTI raw ~170 m must not look like a filter blow-up.
    diverged = int(max_jump > 25.0 or max_coord > 2000.0 or not math.isfinite(max_coord))

    print(
        f"poses={len(poses)} path_m={path_m:.2f} span_m={span:.2f} "
        f"max_jump_m={max_jump:.2f} max_coord_m={max_coord:.2f} "
        f"max_gap_s={max_gap:.4f} diverged={diverged}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
