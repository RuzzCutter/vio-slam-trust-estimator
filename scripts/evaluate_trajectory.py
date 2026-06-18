#!/usr/bin/env python3
"""Evaluate estimated trajectory against ground truth using evo."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def parse_evo_rmse(stdout: str) -> float | None:
    match = re.search(r"^\s*rmse\s+([\d.eE+-]+)\s*$", stdout, re.MULTILINE)
    return float(match.group(1)) if match else None


def euroc_gt_to_tum(csv_path: Path, out_path: Path) -> None:
    import pandas as pd

    df = pd.read_csv(csv_path)
    tum = df.iloc[:, [0, 1, 2, 3, 4, 5, 6, 7]].copy()
    tum.iloc[:, 0] = tum.iloc[:, 0] * 1e-9
    tum.columns = ["timestamp", "x", "y", "z", "qx", "qy", "qz", "qw"]
    tum = tum[["timestamp", "x", "y", "z", "qx", "qy", "qz", "qw"]]
    tum.to_csv(out_path, sep=" ", index=False, header=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--est", type=Path, required=True, help="Estimated trajectory (TUM format)")
    parser.add_argument("--gt", type=Path, required=True, help="Ground truth (TUM, OpenVINS txt, or EuRoC CSV)")
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

    ape = run([
        "evo_ape", "tum", str(gt_path), str(args.est),
        "-va", "--align", "--correct_scale",
        "--save_results", str(ape_zip),
    ])
    rpe = run([
        "evo_rpe", "tum", str(gt_path), str(args.est),
        "-va", "--align", "--correct_scale", "--delta", "1", "--delta_unit", "m",
        "--save_results", str(rpe_zip),
    ])

    # Echo evo tables for the user / log file
    print(ape.stdout)
    if ape.stderr:
        print(ape.stderr, file=sys.stderr)
    print(rpe.stdout)
    if rpe.stderr:
        print(rpe.stderr, file=sys.stderr)

    ape_rmse = parse_evo_rmse(ape.stdout)
    rpe_rmse = parse_evo_rmse(rpe.stdout)

    summary = args.out_dir / "summary.txt"
    with summary.open("w", encoding="utf-8") as f:
        f.write(f"ape_rmse_m={ape_rmse}\n" if ape_rmse is not None else "ape_rmse_m=nan\n")
        f.write(f"rpe_rmse_m={rpe_rmse}\n" if rpe_rmse is not None else "rpe_rmse_m=nan\n")
        f.write(f"est={args.est}\n")
        f.write(f"gt={gt_path}\n")

    if ape_rmse is not None:
        print(f"\nAPE RMSE: {ape_rmse:.4f} m")
    if rpe_rmse is not None:
        print(f"RPE RMSE: {rpe_rmse:.4f} m")
    print(f"Results saved to {args.out_dir}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print("evo not found. Activate venv: source aspiranture/venv/bin/activate", file=sys.stderr)
        raise SystemExit(1) from exc
    except subprocess.CalledProcessError as exc:
        print(exc.stdout or "", end="")
        print(exc.stderr or "", file=sys.stderr, end="")
        raise SystemExit(exc.returncode) from exc
