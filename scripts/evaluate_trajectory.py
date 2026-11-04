#!/usr/bin/env python3
"""Evaluate estimated trajectory against ground truth using evo."""

from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def first_tum_timestamp(path: Path) -> float | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts:
            try:
                return float(parts[0])
            except ValueError:
                return None
    return None


def _np_load_bytes(data: bytes) -> np.ndarray:
    return np.load(io.BytesIO(data), allow_pickle=False)


def load_evo_ape_arrays(ape_zip: Path) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    """Return (error_array, timestamps, seconds_from_start) from an evo result zip."""
    errors = times = seconds = None
    try:
        from evo.tools import file_interface  # type: ignore

        result = file_interface.load_res_file(str(ape_zip))
        arrays = getattr(result, "np_arrays", {}) or {}
        if "error_array" in arrays:
            errors = np.asarray(arrays["error_array"], dtype=float)
        if "timestamps" in arrays:
            times = np.asarray(arrays["timestamps"], dtype=float)
        if "seconds_from_start" in arrays:
            seconds = np.asarray(arrays["seconds_from_start"], dtype=float)
        if errors is not None:
            return errors, times, seconds
    except Exception:
        pass

    if not ape_zip.is_file():
        return None, None, None
    try:
        with zipfile.ZipFile(ape_zip) as zf:
            names = {Path(n).name: n for n in zf.namelist()}
            if "error_array.npy" in names:
                errors = _np_load_bytes(zf.read(names["error_array.npy"])).astype(float)
            if "timestamps.npy" in names:
                times = _np_load_bytes(zf.read(names["timestamps.npy"])).astype(float)
            if "seconds_from_start.npy" in names:
                seconds = _np_load_bytes(zf.read(names["seconds_from_start.npy"])).astype(float)
            if errors is None and "error_array.npz" in names:
                loaded = np.load(io.BytesIO(zf.read(names["error_array.npz"])))
                key = "error_array" if "error_array" in loaded.files else loaded.files[0]
                errors = np.asarray(loaded[key], dtype=float)
    except Exception:
        return None, None, None
    return errors, times, seconds


def export_pose_errors(ape_zip: Path, est: Path, out_csv: Path) -> int:
    """Write per-pose ATE after Sim(3) as CSV columns t,e_ate_m. Returns row count."""
    errors, times, seconds = load_evo_ape_arrays(ape_zip)
    if errors is None or errors.size == 0:
        return 0
    if times is None or times.size != errors.size:
        if seconds is not None and seconds.size == errors.size:
            t0 = first_tum_timestamp(est) or 0.0
            times = t0 + seconds
        else:
            t0 = first_tum_timestamp(est) or 0.0
            times = t0 + np.arange(errors.size, dtype=float)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["t", "e_ate_m"])
        for t, e in zip(times.tolist(), errors.tolist(), strict=False):
            writer.writerow([f"{t:.9f}", f"{e:.9f}"])
    return int(errors.size)


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
    parser.add_argument(
        "--se3",
        "--no-scale",
        action="store_true",
        help="Align SE(3) without scale correction (default is Sim(3) --correct_scale)",
    )
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
    align = ["-va", "--align"]
    if not args.se3:
        align.append("--correct_scale")

    ape = run([
        "evo_ape", "tum", str(gt_path), str(args.est),
        *align,
        "--t_max_diff", "0.05",
        "--save_results", str(ape_zip),
    ])
    rpe = run([
        "evo_rpe", "tum", str(gt_path), str(args.est),
        *align, "--delta", "1", "--delta_unit", "m",
        "--t_max_diff", "0.05",
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

    pose_csv = args.out_dir / "pose_errors.csv"
    n_pose = export_pose_errors(ape_zip, args.est, pose_csv)
    if n_pose:
        with summary.open("a", encoding="utf-8") as f:
            f.write(f"pose_errors={pose_csv}\n")
            f.write(f"n_pose_errors={n_pose}\n")
        print(f"Per-pose ATE: {n_pose} rows → {pose_csv}")
    elif ape_zip.is_file():
        print("Per-pose ATE: could not read error_array from ape.zip", file=sys.stderr)

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
