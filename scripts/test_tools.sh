#!/usr/bin/env bash
# Full toolchain verification before trust_estimator implementation.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

PASS=0
FAIL=0
WARN=0

section() { echo ""; echo "######## $* ########"; }

ok()   { echo "[OK]   $*"; PASS=$((PASS + 1)); }
fail() { echo "[FAIL] $*"; FAIL=$((FAIL + 1)); }
warn() { echo "[WARN] $*"; WARN=$((WARN + 1)); }

check_cmd() {
  local name="$1"
  shift
  if command -v "$1" &>/dev/null; then
    ok "${name}: $($1 --version 2>/dev/null | head -1 || echo found)"
  else
    fail "${name}: not found ($1)"
  fi
}

check_ros_pkg() {
  local pkg="$1"
  if ros2 pkg prefix "${pkg}" &>/dev/null && \
     [[ -d "$(ros2 pkg prefix "${pkg}")/share/${pkg}" ]]; then
    ok "ros2 package ${pkg}"
  elif dpkg -l "ros-jazzy-${pkg//_/-}" &>/dev/null 2>&1; then
    ok "ros2 package ${pkg} (apt)"
  else
    fail "ros2 package ${pkg}"
  fi
}

check_ceres() {
  if pkg-config --exists ceres 2>/dev/null; then
    ok "ceres: $(pkg-config --modversion ceres)"
  elif [[ -f /usr/lib/x86_64-linux-gnu/cmake/Ceres/CeresConfig.cmake ]] || \
       compgen -G "/usr/lib/*/cmake/Ceres/CeresConfig.cmake" >/dev/null; then
    ok "ceres: libceres-dev (cmake)"
  elif dpkg -s libceres-dev &>/dev/null; then
    ok "ceres: $(dpkg -s libceres-dev | awk '/^Version:/{print $2}')"
  else
    fail "ceres: not found"
  fi
}

section "1. System dependencies"
check_cmd "gcc" g++
check_cmd "cmake" cmake
check_cmd "colcon" colcon
check_ceres
pkg-config --exists opencv4 && ok "opencv4: $(pkg-config --modversion opencv4)" || warn "opencv4 pkg-config missing (may still work)"

section "2. ROS 2 Jazzy"
source_ros
check_cmd "ros2" ros2
check_ros_pkg "image_transport"
check_ros_pkg "cv_bridge"

section "3. OpenVINS workspace"
if require_ws_built; then
  ok "ov_msckf package installed"
  for bin in run_subscribe_msckf run_simulation; do
    if ros2 pkg prefix ov_msckf &>/dev/null && \
       [[ -x "$(ros2 pkg prefix ov_msckf)/lib/ov_msckf/${bin}" ]]; then
      ok "binary ${bin}"
    else
      fail "binary ${bin}"
    fi
  done
else
  fail "ws_vins not built"
fi

section "4. Python / evo"
source_venv
python3 -c "import numpy, scipy, pandas, cv2" && ok "python: numpy scipy pandas cv2" || fail "python imports"
if command -v evo_ape &>/dev/null; then
  ok "evo_ape installed"
else
  warn "evo_ape not in PATH (activate venv)"
fi

section "5. Smoke tests (OpenVINS runtime)"
if bash "${SCRIPT_DIR}/test_smoke.sh"; then
  ok "test_smoke.sh"
else
  fail "test_smoke.sh"
fi

section "6. Dataset readiness"
DATA_ROOT="$(aspiranture_root)/datasets"
if [[ -d "${DATA_ROOT}" ]]; then
  found=0
  for seq in MH_01_easy MH_04_difficult MH_05_difficult; do
    if compgen -G "${DATA_ROOT}/euroc/${seq}*" >/dev/null || \
       compgen -G "${DATA_ROOT}/euroc/*${seq}*" >/dev/null; then
      ok "EuRoC ${seq} present"
      found=$((found + 1))
    fi
  done
  if [[ "${found}" -eq 0 ]]; then
    warn "No EuRoC sequences in ${DATA_ROOT} — run scripts/download_datasets.sh"
  fi
else
  warn "datasets/ not created yet"
fi

avail_gb=$(df -BG "$(aspiranture_root)" | awk 'NR==2 {gsub(/G/,"",$4); print $4}')
if [[ "${avail_gb:-0}" -ge 30 ]]; then
  ok "disk free: ${avail_gb} GB (enough for minimal set)"
elif [[ "${avail_gb:-0}" -ge 15 ]]; then
  warn "disk free: ${avail_gb} GB (one EuRoC sequence OK)"
else
  fail "disk free: ${avail_gb} GB (too low)"
fi

section "Summary"
echo "Passed: ${PASS}  Failed: ${FAIL}  Warnings: ${WARN}"
[[ "${FAIL}" -eq 0 ]]
