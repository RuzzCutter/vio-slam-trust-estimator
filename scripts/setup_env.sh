#!/usr/bin/env bash
# Install system dependencies for OpenVINS + experiment pipeline on Ubuntu 24.04 / ROS 2 Jazzy.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash $0"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y \
  libceres-dev \
  libboost-all-dev \
  python3-pip \
  python3-venv \
  python3-pandas \
  python3-matplotlib \
  python3-seaborn \
  ros-jazzy-desktop \
  ros-jazzy-image-transport \
  ros-jazzy-image-transport-plugins \
  ros-jazzy-cv-bridge \
  ros-jazzy-tf2-geometry-msgs \
  ros-jazzy-message-filters \
  ros-jazzy-rosbag2-storage-default-plugins \
  ros-jazzy-rosbag2-compression-zstd \
  time

echo ""
echo "System packages installed."
echo "Next steps (as regular user):"
echo "  source /opt/ros/jazzy/setup.bash"
echo "  cd /home/g-tancyura/aspiranture/ws_vins && colcon build --symlink-install"
echo "  source /home/g-tancyura/aspiranture/venv/bin/activate"
