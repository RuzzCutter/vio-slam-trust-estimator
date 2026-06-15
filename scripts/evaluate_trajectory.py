#!/usr/bin/env python3
"""Evaluate estimated trajectory against ground truth using evo."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def euroc_gt_to_tum(csv_path: Path, out_path: Path) -> None:
    import pandas as pd

    df = pd.read_csv(csv_path)
    # EuRoC GT: timestamp [ns], p_x, p_y, p_z, q_w, q_x, q_y, q_z
    tum = df.iloc[:, [0, 1, 2, 3, 4, 5, 6, 7]].copy()
    tum.iloc[:, 0] = tum.iloc[:, 0] * 1e-9
    tum.columns = ["timestamp", "x", "y", "z", "qx", "qy", "qz", "qw"]
    tum = tum[["timestamp", "x", "y", "z", "qx", "qy", "qz", "qw"]]
    tum.to_csv(out_path, sep=" ", index=False, header=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--est", type=Path, required=True, help="Estimated trajectory (TUM format)")
    parser.add_argument("--gt", type=Path, required=True, help="Ground truth (TUM or EuRoC CSV)")
    parser.add_argument("--out-dir", type=Path, default=Path("results"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    gt_tum = args.out_dir / "gt_tum.txt"

    if args.gt.suffix.lower() == ".csv":
        euroc_gt_to_tum(args.gt, gt_tum)
        gt_path = gt_tum
    else:
        gt_path = args.gt

    ape_zip = args.out_dir / "ape.zip"
    rpe_zip = args.out_dir / "rpe.zip"

    run([
        "evo_ape", "tum", str(gt_path), str(args.est),
        "-va", "--align", "--correct_scale",
        "--save_results", str(ape_zip),
    ])
    run([
        "evo_rpe", "tum", str(gt_path), str(args.est),
        "-va", "--align", "--correct_scale", "--delta", "1", "--delta_unit", "m",
        "--save_results", str(rpe_zip),
    ])
    print(f"Results saved to {args.out_dir}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print("evo not found. Activate venv: source aspiranture/venv/bin/activate", file=sys.stderr)
        raise SystemExit(1) from exc
