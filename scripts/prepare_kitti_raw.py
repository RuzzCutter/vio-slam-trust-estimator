#!/usr/bin/env python3
"""KITTI raw (synced+rectified, gray stereo + OXTS IMU) → OpenVINS kalibr, GT, ROS2 bag.

Sequence default: 2011_09_30_drive_0028 (has IMU; not odometry 00).

  python3 scripts/prepare_kitti_raw.py --calib-dir datasets/kitti/2011_09_30
  python3 scripts/prepare_kitti_raw.py --sync-dir datasets/kitti/2011_09_30/2011_09_30_drive_0028_sync --write-bag
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "ws_vins/src/open_vins/config/kitti_raw"
GT_DIR = ROOT / "ws_vins/src/open_vins/ov_data/kitti_raw"


def _load_rigid(path: Path) -> np.ndarray:
    r_vals: list[float] = []
    t_vals: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("R:"):
            r_vals = [float(x) for x in line.split()[1:]]
        elif line.startswith("T:"):
            t_vals = [float(x) for x in line.split()[1:]]
    t = np.eye(4)
    t[:3, :3] = np.array(r_vals, dtype=float).reshape(3, 3)
    t[:3, 3] = np.array(t_vals, dtype=float)
    return t


def _load_cam_to_cam(path: Path) -> dict[str, np.ndarray]:
    data: dict[str, np.ndarray] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        key = key.strip()
        if key in {"calib_time", "corner_dist"}:
            continue
        try:
            nums = [float(x) for x in rest.split()]
        except ValueError:
            continue
        data[key] = np.array(nums, dtype=float)
    return data


def write_kalibr_from_calib(calib_dir: Path, out_yaml: Path) -> None:
    """T_imu_cam = inv(T_cam_rect_imu), T_cam_rect_imu = R_rect @ T_cam_velo @ T_velo_imu."""
    t_velo_imu = _load_rigid(calib_dir / "calib_imu_to_velo.txt")
    velo_cam = _load_rigid(calib_dir / "calib_velo_to_cam.txt")
    cam = _load_cam_to_cam(calib_dir / "calib_cam_to_cam.txt")
    r_rect = cam["R_rect_00"].reshape(3, 3)
    t_rect = np.eye(4)
    t_rect[:3, :3] = r_rect
    p_rect0 = cam["P_rect_00"].reshape(3, 4)
    p_rect1 = cam["P_rect_01"].reshape(3, 4)
    fu, fv, cu, cv = float(p_rect0[0, 0]), float(p_rect0[1, 1]), float(p_rect0[0, 2]), float(p_rect0[1, 2])
    baseline = -float(p_rect1[0, 3]) / fu
    s = cam.get("S_rect_00", np.array([1242.0, 375.0]))
    w, h = int(s[0]), int(s[1])

    t_cam0_imu = t_rect @ velo_cam @ t_velo_imu
    t_cam1_imu = t_cam0_imu.copy()
    # cam1 is to the right of cam0 in the camera frame: p_C1 = p_C0 - (b, 0, 0)
    t_cam1_imu[0, 3] -= baseline
    t_imu_cam0 = np.linalg.inv(t_cam0_imu)
    t_imu_cam1 = np.linalg.inv(t_cam1_imu)

    def fmt_t(mat: np.ndarray) -> str:
        rows = []
        for i in range(4):
            rows.append("    - [" + ", ".join(f"{mat[i, j]:.8f}" for j in range(4)) + "]")
        return "\n".join(rows)

    text = f"""%YAML:1.0
# Generated from {calib_dir}
cam0:
  T_imu_cam:
{fmt_t(t_imu_cam0)}
  cam_overlaps: [1]
  camera_model: pinhole
  distortion_coeffs: [0.0, 0.0, 0.0, 0.0]
  distortion_model: radtan
  intrinsics: [{fu:.6f}, {fv:.6f}, {cu:.6f}, {cv:.6f}]
  resolution: [{w}, {h}]
  rostopic: /cam0/image_raw
cam1:
  T_imu_cam:
{fmt_t(t_imu_cam1)}
  cam_overlaps: [0]
  camera_model: pinhole
  distortion_coeffs: [0.0, 0.0, 0.0, 0.0]
  distortion_model: radtan
  intrinsics: [{fu:.6f}, {fv:.6f}, {cu:.6f}, {cv:.6f}]
  resolution: [{w}, {h}]
  rostopic: /cam1/image_raw
"""
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.write_text(text, encoding="utf-8")


def oxts_to_tum(oxts_dir: Path, out_txt: Path) -> int:
    """KITTI OXTS (lat/lon/alt, roll/pitch/yaw) → TUM trajectory (world ENU-like)."""
    data_dir = oxts_dir / "data"
    times = (oxts_dir / "timestamps.txt").read_text(encoding="utf-8").splitlines()
    files = sorted(data_dir.glob("*.txt"))
    if not files:
        raise SystemExit(f"no OXTS data in {data_dir}")
    lat0 = lon0 = alt0 = None
    lines_out: list[str] = []
    scale = None
    for stamp_line, fpath in zip(times, files):
        parts = fpath.read_text(encoding="utf-8").split()
        lat, lon, alt = float(parts[0]), float(parts[1]), float(parts[2])
        roll, pitch, yaw = float(parts[3]), float(parts[4]), float(parts[5])
        if lat0 is None:
            lat0, lon0, alt0 = lat, lon, alt
            scale = math.cos(math.radians(lat0))
        assert scale is not None and alt0 is not None
        x = scale * math.radians(lon - lon0) * 6378137.0
        y = math.radians(lat - lat0) * 6378137.0
        z = alt - alt0
        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy, sy = math.cos(yaw), math.sin(yaw)
        rot = np.array(
            [
                [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                [-sp, cp * sr, cp * cr],
            ]
        )
        # IMU to world; TUM wants qx qy qz qw
        from scipy.spatial.transform import Rotation

        qx, qy, qz, qw = Rotation.from_matrix(rot).as_quat()
        t = stamp_line.strip().replace(" ", "T")
        # timestamps.txt is date; use incremental seconds from first if parse fails
        lines_out.append(f"{len(lines_out) * 0.1:.6f} {x:.6f} {y:.6f} {z:.6f} {qx:.6f} {qy:.6f} {qz:.6f} {qw:.6f}")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    return len(lines_out)


def write_ros2_bag(sync_dir: Path, out_bag: Path) -> None:
    import cv2
    from rosbags.rosbag2 import Writer
    from rosbags.typesys import Stores, get_typestore
    from rosbags.typesys.stores.ros2_jazzy import sensor_msgs__msg__Image as Image
    from rosbags.typesys.stores.ros2_jazzy import sensor_msgs__msg__Imu as Imu
    from rosbags.typesys.stores.ros2_jazzy import std_msgs__msg__Header as Header
    from rosbags.typesys.stores.ros2_jazzy import builtin_interfaces__msg__Time as Time
    from rosbags.typesys.stores.ros2_jazzy import geometry_msgs__msg__Vector3 as Vector3
    from rosbags.typesys.stores.ros2_jazzy import geometry_msgs__msg__Quaternion as Quaternion

    typestore = get_typestore(Stores.ROS2_JAZZY)
    img0_dir = sync_dir / "image_00" / "data"
    img1_dir = sync_dir / "image_01" / "data"
    oxts_dir = sync_dir / "oxts" / "data"
    img_times = (sync_dir / "image_00" / "timestamps.txt").read_text(encoding="utf-8").splitlines()
    oxts_times = (sync_dir / "oxts" / "timestamps.txt").read_text(encoding="utf-8").splitlines()
    img0_files = sorted(img0_dir.glob("*.png"))
    img1_files = sorted(img1_dir.glob("*.png"))
    oxts_files = sorted(oxts_dir.glob("*.txt"))

    def ts_ns(line: str, idx: int) -> int:
        # KITTI timestamps are wall-clock; use 10 Hz index for bag time
        return int(idx * 1e8)

    n_oxts = min(len(oxts_files), len(img0_files))
    t_cam = np.arange(len(img0_files), dtype=float) * 0.1
    ax = np.zeros(n_oxts)
    ay = np.zeros(n_oxts)
    az = np.zeros(n_oxts)
    wx = np.zeros(n_oxts)
    wy = np.zeros(n_oxts)
    wz = np.zeros(n_oxts)
    for i in range(n_oxts):
        parts = oxts_files[i].read_text(encoding="utf-8").split()
        ax[i], ay[i], az[i] = float(parts[11]), float(parts[12]), float(parts[13])
        wx[i], wy[i], wz[i] = float(parts[17]), float(parts[18]), float(parts[19])
    t_oxts = t_cam[:n_oxts]
    imu_hz = 100.0
    t_end = float(t_oxts[-1]) if n_oxts else 0.0
    t_imu = np.arange(0.0, t_end + 1e-9, 1.0 / imu_hz)
    ax_i = np.interp(t_imu, t_oxts, ax)
    ay_i = np.interp(t_imu, t_oxts, ay)
    az_i = np.interp(t_imu, t_oxts, az)
    wx_i = np.interp(t_imu, t_oxts, wx)
    wy_i = np.interp(t_imu, t_oxts, wy)
    wz_i = np.interp(t_imu, t_oxts, wz)

    events: list[tuple[int, str, object]] = []
    for i, (f0, f1) in enumerate(zip(img0_files, img1_files)):
        t = ts_ns(img_times[i] if i < len(img_times) else "", i)
        for fpath, fid in ((f0, "cam0"), (f1, "cam1")):
            img = cv2.imread(str(fpath), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            header = Header(stamp=Time(sec=t // 1_000_000_000, nanosec=t % 1_000_000_000), frame_id=fid)
            msg = Image(
                header=header,
                height=img.shape[0],
                width=img.shape[1],
                encoding="mono8",
                is_bigendian=0,
                step=int(img.shape[1]),
                data=np.ascontiguousarray(img).reshape(-1),
            )
            events.append((t, fid, msg))
    for ti, axi, ayi, azi, wxi, wyi, wzi in zip(t_imu, ax_i, ay_i, az_i, wx_i, wy_i, wz_i):
        t = int(round(ti * 1e9))
        imu = Imu(
            header=Header(stamp=Time(sec=t // 1_000_000_000, nanosec=t % 1_000_000_000), frame_id="imu0"),
            orientation=Quaternion(x=0.0, y=0.0, z=0.0, w=1.0),
            orientation_covariance=np.array([-1.0] + [0.0] * 8),
            angular_velocity=Vector3(x=float(wxi), y=float(wyi), z=float(wzi)),
            angular_velocity_covariance=np.zeros(9),
            linear_acceleration=Vector3(x=float(axi), y=float(ayi), z=float(azi)),
            linear_acceleration_covariance=np.zeros(9),
        )
        events.append((t, "imu0", imu))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "imu0" else 1))

    out_bag.parent.mkdir(parents=True, exist_ok=True)
    with Writer(out_bag, version=9) as writer:
        c0 = writer.add_connection("/cam0/image_raw", Image.__msgtype__, typestore=typestore)
        c1 = writer.add_connection("/cam1/image_raw", Image.__msgtype__, typestore=typestore)
        ci = writer.add_connection("/imu0", Imu.__msgtype__, typestore=typestore)
        conn_by = {"cam0": c0, "cam1": c1, "imu0": ci}
        type_by = {"cam0": Image.__msgtype__, "cam1": Image.__msgtype__, "imu0": Imu.__msgtype__}
        for t, key, msg in events:
            writer.write(conn_by[key], t, typestore.serialize_cdr(msg, type_by[key]))
    _ = oxts_times


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare KITTI raw for OpenVINS")
    parser.add_argument("--calib-dir", type=Path, help="Folder with calib_cam_to_cam.txt etc.")
    parser.add_argument("--sync-dir", type=Path, help="..._sync folder (image_00, oxts)")
    parser.add_argument("--write-bag", action="store_true")
    parser.add_argument("--seq-id", default="kitti_2011_09_26_drive_0009")
    args = parser.parse_args()
    if args.calib_dir:
        write_kalibr_from_calib(args.calib_dir, CFG / "kalibr_imucam_chain.yaml")
        print(f"Wrote {CFG / 'kalibr_imucam_chain.yaml'}")
    if args.sync_dir:
        oxts = args.sync_dir / "oxts"
        gt = GT_DIR / f"{args.seq_id}.txt"
        n = oxts_to_tum(oxts, gt)
        print(f"GT {n} poses → {gt}")
        if args.write_bag:
            bag = ROOT / "datasets" / "kitti" / f"{args.seq_id}_ros2"
            write_ros2_bag(args.sync_dir, bag)
            print(f"BAG {bag}")
    if not args.calib_dir and not args.sync_dir:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
