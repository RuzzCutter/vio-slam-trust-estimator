#!/usr/bin/env python3
"""Build a degraded copy of a EuRoC ROS2 bag (camera images only; IMU unchanged).

Examples:
  python3 scripts/degrade_ros2_bag.py \\
    --input datasets/euroc/MH_04_difficult_ros2 \\
    --output datasets/euroc/degraded/MH_04_difficult_gaussian5_ros2 \\
    --type gaussian --level 5
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from rosbags.rosbag2 import Reader, Writer
from rosbags.typesys import Stores, get_typestore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from degrade_dataset import DEGRADERS  # noqa: E402

IMAGE_TOPICS = {"/cam0/image_raw", "/cam1/image_raw"}


def degrade_image(img: np.ndarray, dtype: str, level: float) -> np.ndarray:
    degrade = DEGRADERS[dtype]
    if img.ndim == 2:
        return degrade(img, level)
    return degrade(img, level)


def degrade_bag(
    input_dir: Path,
    output_dir: Path,
    dtype: str,
    level: float,
    *,
    force: bool = False,
) -> None:
    if output_dir.exists():
        if force:
            shutil.rmtree(output_dir)
        elif any(output_dir.glob("*.db3")):
            print(f"Already exists: {output_dir}")
            return

    typestore = get_typestore(Stores.ROS2_JAZZY)
    conn_out: dict[int, int] = {}
    n_img = 0
    n_all = 0

    output_dir.parent.mkdir(parents=True, exist_ok=True)

    with Reader(input_dir) as reader:
        with Writer(output_dir, version=9) as writer:
            for conn in reader.connections:
                conn_out[conn.id] = writer.add_connection(
                    conn.topic,
                    conn.msgtype,
                    typestore=typestore,
                    serialization_format=conn.ext.serialization_format,
                )

            for conn, timestamp, rawdata in reader.messages():
                if conn.topic in IMAGE_TOPICS:
                    msg = typestore.deserialize_cdr(rawdata, conn.msgtype)
                    img = np.asarray(msg.data, dtype=np.uint8).reshape((msg.height, msg.width))
                    out = degrade_image(img, dtype, level)
                    msg.data = np.ascontiguousarray(out).reshape(-1).copy()
                    rawdata = typestore.serialize_cdr(msg, conn.msgtype)
                    n_img += 1
                    if n_img % 500 == 0:
                        print(f"  images: {n_img}", flush=True)

                writer.write(conn_out[conn.id], timestamp, rawdata)
                n_all += 1

    print(f"Done: {n_all} messages ({n_img} images) -> {output_dir}")


def degraded_bag_path(data_root: Path, seq: str, dtype: str, level: float) -> Path:
    level_tag = str(level).replace(".", "p")
    return data_root / "euroc" / "degraded" / f"{seq}_{dtype}{level_tag}_ros2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Degrade camera topics in a ROS2 bag")
    parser.add_argument("--input", type=Path, required=True, help="Source bag directory")
    parser.add_argument("--output", type=Path, help="Output bag directory (default: auto under degraded/)")
    parser.add_argument("--seq", help="Sequence name for auto output path (e.g. MH_04_difficult)")
    parser.add_argument("--type", choices=sorted(DEGRADERS), required=True)
    parser.add_argument("--level", type=float, required=True)
    parser.add_argument("--force", action="store_true", help="Rebuild even if output exists")
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"ERROR: input bag not found: {args.input}", file=sys.stderr)
        return 1

    out = args.output
    if out is None:
        if not args.seq:
            print("ERROR: --output or --seq required", file=sys.stderr)
            return 1
        data_root = ROOT / "datasets"
        out = degraded_bag_path(data_root, args.seq, args.type, args.level)

    degrade_bag(args.input, out, args.type, args.level, force=args.force)
    print(f"DEGRADED_BAG={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
