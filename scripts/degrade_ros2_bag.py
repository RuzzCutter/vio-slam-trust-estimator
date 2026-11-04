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

STALE_PERIOD_S = 10.0
BAG_TYPES = sorted(set(DEGRADERS) | {"stale", "lag"})


def stale_in_window(
    t: float,
    t0: float,
    window_s: float,
    period_s: float = STALE_PERIOD_S,
    after_s: float = 0.0,
) -> bool:
    if window_s <= 0:
        return False
    if t - t0 < after_s:
        return False
    t_ref = t0 + after_s
    phase = (t - t_ref) % period_s
    return 0.0 <= phase < window_s


def parse_degrade_spec(spec: str) -> tuple[str, float, float]:
    """Return (dtype, level, after_s). after_s is 0 unless stale:W:after=T."""
    parts = spec.split(":")
    dtype = parts[0]
    level = float(parts[1]) if len(parts) > 1 else 0.0
    after_s = 0.0
    for p in parts[2:]:
        if p.startswith("after="):
            after_s = float(p.split("=", 1)[1])
    return dtype, level, after_s

def _is_raw_image_topic(conn) -> bool:
    mt = getattr(conn, "msgtype", "") or ""
    return mt.endswith("/Image") and "Compressed" not in mt


def degrade_image(img: np.ndarray, dtype: str, level: float) -> np.ndarray:
    degrade = DEGRADERS[dtype]
    return degrade(img, level)


def _reshape_image(msg) -> np.ndarray:
    enc = getattr(msg, "encoding", "mono8") or "mono8"
    raw = np.asarray(msg.data, dtype=np.uint8)
    if enc == "mono16":
        return raw.view(np.uint16).reshape((msg.height, msg.width))
    if enc in ("bgr8", "rgb8"):
        return raw.reshape((msg.height, msg.width, 3))
    if enc in ("bgra8", "rgba8"):
        return raw.reshape((msg.height, msg.width, 4))
    return raw.reshape((msg.height, msg.width))


def _pack_image_data(img: np.ndarray) -> np.ndarray:
    arr = np.ascontiguousarray(img)
    if arr.dtype == np.uint16:
        return arr.view(np.uint8).reshape(-1)
    return arr.reshape(-1)


def degrade_bag(
    input_dir: Path,
    output_dir: Path,
    dtype: str,
    level: float,
    *,
    force: bool = False,
    after_s: float = 0.0,
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

            t0_s: float | None = None
            freeze_data: dict[int, np.ndarray] = {}
            in_window: dict[int, bool] = {}
            lag_buf: dict[int, list[tuple[float, np.ndarray]]] = {}

            for conn, timestamp, rawdata in reader.messages():
                if _is_raw_image_topic(conn):
                    t_s = timestamp * 1e-9
                    if t0_s is None:
                        t0_s = t_s
                    msg = typestore.deserialize_cdr(rawdata, conn.msgtype)
                    if dtype == "stale":
                        window = stale_in_window(t_s, t0_s, float(level), after_s=after_s)
                        cid = conn.id
                        if window:
                            if not in_window.get(cid, False):
                                freeze_data[cid] = np.array(msg.data, copy=True)
                                in_window[cid] = True
                            msg.data = freeze_data[cid]
                            rawdata = typestore.serialize_cdr(msg, conn.msgtype)
                        else:
                            in_window[cid] = False
                    elif dtype == "lag":
                        cid = conn.id
                        buf = lag_buf.setdefault(cid, [])
                        data_now = np.array(msg.data, copy=True)
                        buf.append((t_s, data_now))
                        tau = float(level)
                        cutoff = t_s - tau - 1.0
                        while buf and buf[0][0] < cutoff:
                            buf.pop(0)
                        src = None
                        target = t_s - tau
                        for ts_i, dat in reversed(buf):
                            if ts_i <= target:
                                src = dat
                                break
                        if src is not None:
                            msg.data = src
                            rawdata = typestore.serialize_cdr(msg, conn.msgtype)
                    else:
                        img = _reshape_image(msg)
                        out = degrade_image(img, dtype, level)
                        msg.data = _pack_image_data(out).copy()
                        rawdata = typestore.serialize_cdr(msg, conn.msgtype)
                    n_img += 1
                    if n_img % 500 == 0:
                        print(f"  images: {n_img}", flush=True)

                writer.write(conn_out[conn.id], timestamp, rawdata)
                n_all += 1

    print(f"Done: {n_all} messages ({n_img} images) -> {output_dir}")


def level_cache_tag(level: float) -> str:
    if float(level).is_integer():
        return str(int(level))
    return str(level).replace(".", "p")


def degraded_bag_path(
    data_root: Path,
    seq: str,
    dtype: str,
    level: float,
    bag_dir: str = "euroc",
    after_s: float = 0.0,
) -> Path:
    tag = f"{seq}_{dtype}{level_cache_tag(level)}"
    if dtype == "stale" and after_s > 0:
        tag = f"{seq}_stale{level_cache_tag(level)}after{level_cache_tag(after_s)}"
    return data_root / bag_dir / "degraded" / f"{tag}_ros2"


def main() -> int:
    parser = argparse.ArgumentParser(description="Degrade camera topics in a ROS2 bag")
    parser.add_argument("--input", type=Path, required=True, help="Source bag directory")
    parser.add_argument("--output", type=Path, help="Output bag directory (default: auto under degraded/)")
    parser.add_argument("--seq", help="Sequence name for auto output path (e.g. MH_04_difficult)")
    parser.add_argument("--type", choices=BAG_TYPES)
    parser.add_argument("--level", type=float)
    parser.add_argument("--spec", help="e.g. stale:1:after=30 or lag:0.5")
    parser.add_argument("--after", type=float, default=0.0, help="stale: freeze only after this many seconds from first image")
    parser.add_argument("--force", action="store_true", help="Rebuild even if output exists")
    args = parser.parse_args()

    dtype = args.type
    level = args.level
    after_s = float(args.after or 0.0)
    if args.spec:
        dtype, level, after_from_spec = parse_degrade_spec(args.spec)
        after_s = after_from_spec if after_from_spec else after_s
    if not dtype or level is None:
        print("ERROR: --type/--level or --spec required", file=sys.stderr)
        return 1

    if not args.input.is_dir():
        print(f"ERROR: input bag not found: {args.input}", file=sys.stderr)
        return 1

    out = args.output
    if out is None:
        if not args.seq:
            print("ERROR: --output or --seq required", file=sys.stderr)
            return 1
        data_root = ROOT / "datasets"
        bag_dir = "euroc"
        try:
            sys.path.insert(0, str(ROOT / "scripts" / "lib"))
            from datasets_registry import query as _reg_query  # noqa: E402

            bag_dir = _reg_query(args.seq, "bag_dir") or "euroc"
        except Exception:
            bag_dir = "euroc"
        out = degraded_bag_path(data_root, args.seq, dtype, float(level), bag_dir=bag_dir, after_s=after_s)

    degrade_bag(args.input, out, dtype, float(level), force=args.force, after_s=after_s)
    print(f"DEGRADED_BAG={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
