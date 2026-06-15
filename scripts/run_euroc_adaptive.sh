#!/usr/bin/env bash
# Run OpenVINS + trust_estimator (adaptive covariance) on EuRoC ROS2 bag.
#
# Usage:
#   bash run_euroc_adaptive.sh MH_01_easy --duration 60
#   bash run_euroc_adaptive.sh MH_01_easy --viz
#   bash run_euroc_adaptive.sh MH_04_difficult
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

SEQ=""
DURATION=""
RVIZ=false
LAUNCH_PID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)
      DURATION="${2:-60}"
      shift 2
      ;;
    --viz) RVIZ=true; shift ;;
    -*) echo "Unknown option: $1" >&2; exit 1 ;;
    *)
      if [[ -z "${SEQ}" ]]; then SEQ="$1"; else echo "Unexpected arg: $1" >&2; exit 1; fi
      shift
      ;;
  esac
done

SEQ="${SEQ:-MH_01_easy}"

declare -A EUROC_START_OFFSET=(
  [MH_01_easy]=40
  [MH_02_easy]=35
  [MH_03_medium]=5
  [MH_04_difficult]=10
  [MH_05_difficult]=5
)
START_OFFSET="${EUROC_START_OFFSET[${SEQ}]:-0}"

source_ros
require_ws_built

DATA_ROOT="${DATA_ROOT:-$(aspiranture_root)/datasets}"
BAG="${DATA_ROOT}/euroc/${SEQ}_ros2"
OUT_DIR="${DATA_ROOT}/results/${SEQ}_adaptive_$(date +%Y%m%d_%H%M%S)"
LAUNCH_FILE="$(aspiranture_root)/launch/euroc_adaptive.launch.py"
mkdir -p "${OUT_DIR}"

if [[ ! -d "${BAG}" ]]; then
  echo "ERROR: ROS2 bag not found: ${BAG}" >&2
  exit 1
fi

TRUST_LOG="${OUT_DIR}/trust_log.csv"
RUN_CONFIG="${OUT_DIR}/estimator_config.yaml"
TRUST_CFG_DIR="$(aspiranture_root)/ws_vins/src/open_vins/config/euroc_mav_trust"
cp "${TRUST_CFG_DIR}/kalibr_imu_chain.yaml" "${OUT_DIR}/"
cp "${TRUST_CFG_DIR}/kalibr_imucam_chain.yaml" "${OUT_DIR}/"
sed "s|trust_log_filepath:.*|trust_log_filepath: \"${TRUST_LOG}\"|" "${TRUST_CFG_DIR}/estimator_config.yaml" > "${RUN_CONFIG}"

echo "Bag:        ${BAG}"
echo "Output:     ${OUT_DIR}"
echo "Trust log:  ${TRUST_LOG}"
echo "RViz:       ${RVIZ}"
if [[ "${START_OFFSET}" != "0" ]]; then
  echo "Skip:       first ${START_OFFSET} s of bag"
fi
echo ""

RVIZ_ARG="rviz_enable:=false"
${RVIZ} && RVIZ_ARG="rviz_enable:=true"
CONFIG_PATH_ARG="config_path:=${RUN_CONFIG}"

PLAY_FLAGS=(--clock --rate 1.0 --disable-keyboard-controls)
if [[ "${START_OFFSET}" != "0" ]]; then
  PLAY_FLAGS+=(--start-offset "${START_OFFSET}")
fi

cleanup() {
  if [[ -n "${LAUNCH_PID}" ]] && kill -0 "${LAUNCH_PID}" 2>/dev/null; then
    kill "${LAUNCH_PID}" 2>/dev/null || true
    wait "${LAUNCH_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

verify_openvins() {
  if ! kill -0 "${LAUNCH_PID}" 2>/dev/null; then
    echo "ERROR: OpenVINS exited early. Log:" >&2
    tail -30 "${OUT_DIR}/openvins.log" >&2
    exit 1
  fi
  if grep -q "process has died" "${OUT_DIR}/openvins.log" 2>/dev/null; then
    echo "ERROR: OpenVINS crashed:" >&2
    tail -20 "${OUT_DIR}/openvins.log" >&2
    exit 1
  fi
}

launch_openvins_background() {
  echo "Launch OpenVINS + trust_estimator${RVIZ:+ + RViz}..."
  # shellcheck disable=SC2086
  ros2 launch "${LAUNCH_FILE}" ${RVIZ_ARG} ${CONFIG_PATH_ARG} > "${OUT_DIR}/openvins.log" 2>&1 &
  LAUNCH_PID=$!
  sleep 8
  verify_openvins
}

play_bag() {
  local log_target="$1"
  local play_cmd=(ros2 bag play "${BAG}" "${PLAY_FLAGS[@]}")

  if [[ -n "${DURATION}" ]]; then
    echo "Playing ${DURATION} s of bag..."
    if [[ "${log_target}" == "tee" ]]; then
      timeout "${DURATION}" "${play_cmd[@]}" 2>&1 | tee "${OUT_DIR}/bag_play.log" || true
    else
      timeout "${DURATION}" "${play_cmd[@]}" > "${OUT_DIR}/bag_play.log" 2>&1 || true
    fi
  else
    echo "Playing full bag..."
    if [[ "${log_target}" == "tee" ]]; then
      "${play_cmd[@]}" 2>&1 | tee "${OUT_DIR}/bag_play.log"
    else
      "${play_cmd[@]}" > "${OUT_DIR}/bag_play.log" 2>&1
    fi
  fi
}

show_summary() {
  sleep 2
  echo ""
  echo "Done. Logs: ${OUT_DIR}"
  echo "--- OpenVINS (last lines) ---"
  grep -aE 'subscribing|init|TIME|trust|failed|error|died|successful' "${OUT_DIR}/openvins.log" | tail -25 \
    || tail -15 "${OUT_DIR}/openvins.log"
  if [[ -f "${TRUST_LOG}" ]]; then
    echo ""
    echo "--- Trust log (last lines) ---"
    tail -5 "${TRUST_LOG}"
  fi
}

if ${RVIZ}; then
  launch_openvins_background
  echo "Starting bag playback..."
  play_bag tee
  show_summary
  exit 0
fi

launch_openvins_background
play_bag file
show_summary
