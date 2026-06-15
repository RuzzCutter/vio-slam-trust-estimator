#!/usr/bin/env bash
# Run OpenVINS baseline on EuRoC ROS2 bag.
#
# Usage:
#   bash run_euroc_baseline.sh MH_01_easy --duration 60   # headless, 60 s playback
#   bash run_euroc_baseline.sh MH_01_easy --viz             # RViz + auto bag (1 terminal)
#   bash run_euroc_baseline.sh MH_01_easy                   # headless, full bag
#   bash run_euroc_baseline.sh --help-manual               # 2-terminal workflow
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

show_manual() {
  cat <<'EOF'
=== Ручной запуск с визуализацией (2 терминала) ===

Терминал 1 — OpenVINS + RViz:
  cd ~/aspiranture
  source scripts/lib.sh && source_ros
  ros2 launch launch/euroc_baseline.launch.py rviz_enable:=true

  В RViz: траектория (path), точки, odometry.
  Окно RViz ищите на панели задач.

Терминал 2 — воспроизведение bag (MH_01: пропуск первых 40 с):
  cd ~/aspiranture
  source scripts/lib.sh && source_ros
  ros2 bag play datasets/euroc/MH_01_easy_ros2 --clock --rate 1.0 --disable-keyboard-controls --start-offset 40

Опционально — трекинг признаков:
  ros2 run rqt_image_view rqt_image_view /ov_msckf/trackhist

=== Один терминал (автозапуск bag) ===

  bash scripts/run_euroc_baseline.sh MH_01_easy --viz
  bash scripts/run_euroc_baseline.sh MH_01_easy --viz --duration 60
EOF
}

SEQ=""
DURATION=""
RVIZ=false
LAUNCH_PID=""
BAG_PID=""

if [[ "${1:-}" == "--help-manual" ]]; then
  show_manual
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)
      DURATION="${2:-60}"
      shift 2
      ;;
    --viz) RVIZ=true; shift ;;
    --help-manual) show_manual; exit 0 ;;
    -*) echo "Unknown option: $1" >&2; exit 1 ;;
    *)
      if [[ -z "${SEQ}" ]]; then SEQ="$1"; else echo "Unexpected arg: $1" >&2; exit 1; fi
      shift
      ;;
  esac
done

SEQ="${SEQ:-MH_01_easy}"

# EuRoC bag start offsets (seconds) — skip pickup / bad KLT at start (OpenVINS run_ros_eth.sh)
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
OUT_DIR="${DATA_ROOT}/results/${SEQ}_baseline_$(date +%Y%m%d_%H%M%S)"
LAUNCH_FILE="$(aspiranture_root)/launch/euroc_baseline.launch.py"
mkdir -p "${OUT_DIR}"

if [[ ! -d "${BAG}" ]]; then
  echo "ERROR: ROS2 bag not found: ${BAG}" >&2
  exit 1
fi

if ${RVIZ} && [[ -z "${DISPLAY:-}" ]]; then
  echo "WARN: DISPLAY not set — RViz may not open (SSH without X11?)." >&2
fi

echo "Bag:     ${BAG}"
echo "Output:  ${OUT_DIR}"
echo "RViz:    ${RVIZ}"
if [[ "${START_OFFSET}" != "0" ]]; then
  echo "Skip:    first ${START_OFFSET} s of bag (EuRoC pickup phase)"
fi
echo ""

RVIZ_ARG="rviz_enable:=false"
${RVIZ} && RVIZ_ARG="rviz_enable:=true"

# Bag player flags: no keyboard (fixes tcsetattr in scripts), sim time via /clock
PLAY_FLAGS=(--clock --rate 1.0 --disable-keyboard-controls)
if [[ "${START_OFFSET}" != "0" ]]; then
  PLAY_FLAGS+=(--start-offset "${START_OFFSET}")
fi

cleanup() {
  if [[ -n "${BAG_PID}" ]] && kill -0 "${BAG_PID}" 2>/dev/null; then
    kill "${BAG_PID}" 2>/dev/null || true
    wait "${BAG_PID}" 2>/dev/null || true
  fi
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
  echo "Launch OpenVINS${RVIZ:+ + RViz} (background)..."
  ros2 launch "${LAUNCH_FILE}" ${RVIZ_ARG} > "${OUT_DIR}/openvins.log" 2>&1 &
  LAUNCH_PID=$!
  echo "Waiting for OpenVINS to start..."
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
    echo "Playing full bag (~3 min for MH_01 after offset)..."
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
  grep -aE 'subscribing|init|TIME|failed|error|died|successful' "${OUT_DIR}/openvins.log" | tail -25 \
    || tail -15 "${OUT_DIR}/openvins.log"
}

if ${RVIZ}; then
  launch_openvins_background
  echo ""
  echo "OpenVINS + RViz ready. Starting bag playback..."
  play_bag tee
  show_summary
  exit 0
fi

launch_openvins_background
play_bag file
show_summary
echo ""
echo "Visualization:"
echo "  bash scripts/run_euroc_baseline.sh ${SEQ} --viz"
echo "  bash scripts/run_euroc_baseline.sh --help-manual"
