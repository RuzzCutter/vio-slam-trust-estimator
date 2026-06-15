#!/usr/bin/env bash
# Quick smoke tests without datasets.
set -euo pipefail

source /opt/ros/jazzy/setup.bash
source /home/g-tancyura/aspiranture/ws_vins/install/setup.bash

echo "=== Test 1: run_simulation (15 s) ==="
CONFIG="$(ros2 pkg prefix ov_msckf)/share/ov_msckf/config/rpng_sim/estimator_config.yaml"
timeout 15 ros2 run ov_msckf run_simulation "$CONFIG" 2>&1 | grep -E 'rmse|init|failed' | tail -5 || true

echo ""
echo "=== Test 2: subscribe node start (5 s, no bag) ==="
timeout 5 ros2 launch ov_msckf subscribe.launch.py config:=euroc_mav rviz_enable:=false 2>&1 | grep -E 'subscribing|ERROR' || true

echo ""
echo "Smoke tests done."
