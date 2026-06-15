#!/usr/bin/env python3
"""Subscribe to OpenVINS pose topic and save trajectory in TUM format."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy


class TrajectoryRecorder(Node):
    def __init__(self, output_path: Path, topic: str) -> None:
        super().__init__("trajectory_recorder")
        self.output_path = output_path
        self.count = 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
        self._file = output_path.open("w", encoding="utf-8")
        self._file.write("# timestamp x y z qx qy qz qw\n")
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=100,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.create_subscription(PoseWithCovarianceStamped, topic, self._callback, qos)
        self.get_logger().info(f"Recording {topic} -> {output_path}")

    def _callback(self, msg: PoseWithCovarianceStamped) -> None:
        stamp = msg.header.stamp
        t = float(stamp.sec) + float(stamp.nanosec) * 1e-9
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        self._file.write(
            f"{t:.9f} {p.x:.9f} {p.y:.9f} {p.z:.9f} "
            f"{q.x:.9f} {q.y:.9f} {q.z:.9f} {q.w:.9f}\n"
        )
        self.count += 1
        if self.count % 100 == 0:
            self._file.flush()

    def close(self) -> None:
        self._file.flush()
        self._file.close()
        self.get_logger().info(f"Saved {self.count} poses to {self.output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Record OpenVINS trajectory to TUM file")
    parser.add_argument("--output", type=Path, required=True, help="Output TUM trajectory path")
    parser.add_argument(
        "--topic",
        default="/ov_msckf/poseimu",
        help="Pose topic (default: /ov_msckf/poseimu)",
    )
    args, ros_args = parser.parse_known_args()

    rclpy.init(args=ros_args)
    node = TrajectoryRecorder(args.output, args.topic)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
