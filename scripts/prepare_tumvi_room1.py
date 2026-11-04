#!/usr/bin/env python3
"""Download TUM-VI room1 ROS1 bag and convert to ROS2.

  python3 scripts/prepare_tumvi_room1.py
  python3 scripts/prepare_tumvi_room1.py --skip-download --bag datasets/tum_vi/dataset-room1_512_16.bag
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://vision.in.tum.de/tumvi/calibrated/512_16/dataset-room1_512_16.bag"
OUT_ROS1 = ROOT / "datasets" / "tum_vi" / "dataset-room1_512_16.bag"
OUT_ROS2 = ROOT / "datasets" / "tum_vi" / "tumvi_room1_ros2"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--bag", type=Path, default=OUT_ROS1)
    parser.add_argument("--out", type=Path, default=OUT_ROS2)
    args = parser.parse_args()
    args.bag.parent.mkdir(parents=True, exist_ok=True)
    if not args.skip_download:
        if not args.bag.is_file():
            print(f"Downloading {URL} → {args.bag}", flush=True)
            rc = subprocess.call(["wget", "-O", str(args.bag), URL])
            if rc != 0:
                return rc
        else:
            print(f"Already have {args.bag}")
    if not args.bag.is_file():
        print(f"Missing ROS1 bag: {args.bag}", file=sys.stderr)
        return 1
    if args.out.is_dir() and any(args.out.glob("*.db3")):
        print(f"Already converted: {args.out}")
        return 0
    cmd = [
        sys.executable,
        "-m",
        "rosbags.convert",
        "--src",
        str(args.bag),
        "--dst",
        str(args.out),
        "--src-typestore",
        "ros1_noetic",
        "--dst-typestore",
        "ros2_jazzy",
    ]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
