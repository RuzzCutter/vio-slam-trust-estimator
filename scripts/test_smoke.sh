#!/usr/bin/env bash
# Quick smoke tests without datasets.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

source_ros
require_ws_built

WS_VINS="$(aspiranture_root)/ws_vins"
PASS=0
FAIL=0

check() {
  local name="$1"
  shift
  echo ""
  echo "=== ${name} ==="
  if "$@"; then
    echo "[OK] ${name}"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] ${name}"
    FAIL=$((FAIL + 1))
  fi
}

test_simulation() {
  local config
  config="$(ros2 pkg prefix ov_msckf)/share/ov_msckf/config/rpng_sim/estimator_config.yaml"
  local out
  # sim_traj_path in rpng_sim config is relative to ws_vins/
  out="$(cd "${WS_VINS}" && timeout 15 ros2 run ov_msckf run_simulation "${config}" 2>&1)" || true
  local cleaned
  cleaned="$(echo "${out}" | sed 's/\x1b\[[0-9;]*m//g')"
  echo "${cleaned}" | grep -E 'RMSE|rmse' | tail -4
  [[ "${cleaned}" == *RMSE* || "${cleaned}" == *rmse* ]]
}

test_subscribe_launch() {
  local out
  out="$(timeout 12 ros2 launch ov_msckf subscribe.launch.py config:=euroc_mav rviz_enable:=false 2>&1)" || true
  echo "${out}" | grep -i 'subscribing' || true
  echo "${out}" | grep -qi 'subscribing to IMU'
}

check "run_simulation (15 s)" test_simulation
check "subscribe.launch (12 s, no bag)" test_subscribe_launch

echo ""
echo "Smoke summary: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
