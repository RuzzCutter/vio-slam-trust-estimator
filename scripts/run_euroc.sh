#!/usr/bin/env bash
# Unified EuRoC experiment runner (baseline or adaptive).
#
# Usage:
#   bash run_euroc.sh baseline MH_01_easy --duration 60
#   bash run_euroc.sh adaptive MH_04_difficult --viz
#   bash run_euroc.sh adaptive MH_01_easy --duration 60 --eval
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"
# shellcheck source=lib/euroc_common.sh
source "${SCRIPT_DIR}/lib/euroc_common.sh"

MODE=""
SEQ=""
DURATION=""
RVIZ=false
EVAL=false
VERBOSE=true
LAUNCH_PID=""
REC_PID=""

usage() {
  cat <<'EOF'
Usage: run_euroc.sh <baseline|adaptive> [SEQUENCE] [OPTIONS]

Sequences (downloaded):
  MH_01_easy, MH_04_difficult, MH_05_difficult

Options:
  --duration SEC   Playback length in seconds (default: full bag)
  --viz            Open RViz + auto-play bag (single terminal)
  --eval           Compute ATE/RPE after run (needs GT + evo)
  --quiet          Less console output
  --help           This help

Examples:
  bash scripts/run_euroc.sh baseline MH_01_easy --duration 60
  bash scripts/run_euroc.sh adaptive MH_04_difficult --duration 120 --eval
  bash scripts/run_euroc.sh adaptive MH_01_easy --viz
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

MODE="$1"
shift
case "${MODE}" in
  baseline|adaptive) ;;
  *)
    echo "ERROR: first argument must be 'baseline' or 'adaptive', got: ${MODE}" >&2
    exit 1
    ;;
esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)
      DURATION="${2:-60}"
      shift 2
      ;;
    --viz) RVIZ=true; shift ;;
    --eval) EVAL=true; shift ;;
    --quiet) VERBOSE=false; shift ;;
    --help|-h) usage; exit 0 ;;
    -*) echo "Unknown option: $1" >&2; exit 1 ;;
    *)
      if [[ -z "${SEQ}" ]]; then SEQ="$1"; else echo "Unexpected arg: $1" >&2; exit 1; fi
      shift
      ;;
  esac
done

SEQ="${SEQ:-MH_01_easy}"
START_OFFSET="${EUROC_START_OFFSET[${SEQ}]:-0}"

source_ros
require_ws_built

DATA_ROOT="${DATA_ROOT:-$(aspiranture_root)/datasets}"
BAG="${DATA_ROOT}/euroc/${SEQ}_ros2"
TAG="${MODE}"
OUT_DIR="${DATA_ROOT}/results/${SEQ}_${TAG}_$(date +%Y%m%d_%H%M%S)"
mkdir -p "${OUT_DIR}"

TRAJ_FILE="${OUT_DIR}/trajectory_tum.txt"
TRUST_LOG="${OUT_DIR}/trust_log.csv"

if [[ "${MODE}" == "baseline" ]]; then
  LAUNCH_FILE="$(aspiranture_root)/launch/euroc_baseline.launch.py"
  CONFIG_PATH_ARG=""
  MODE_LABEL="Baseline (классический OpenVINS, фиксированный шум измерений)"
else
  LAUNCH_FILE="$(aspiranture_root)/launch/euroc_adaptive.launch.py"
  RUN_CONFIG="$(euroc_prepare_adaptive_config "${OUT_DIR}" "${TRUST_LOG}")"
  CONFIG_PATH_ARG="config_path:=${RUN_CONFIG}"
  MODE_LABEL="Adaptive (OpenVINS + trust_estimator, адаптивная ковариация)"
fi

if [[ ! -d "${BAG}" ]]; then
  demo_fail "Bag не найден: ${BAG}"
  echo "  Скачайте: bash scripts/download_datasets.sh minimal --ros2" >&2
  exit 1
fi

if ${RVIZ} && [[ -z "${DISPLAY:-}" ]]; then
  demo_warn "DISPLAY не задан — RViz может не открыться"
fi

if ${VERBOSE}; then
  demo_banner "Прогон EuRoC — ${MODE}"
  demo_kv "Режим" "${MODE_LABEL}"
  demo_kv "Последов." "${SEQ}"
  demo_kv "Bag" "${BAG}"
  demo_kv "Длительность" "$([[ -n "${DURATION}" ]] && echo "${DURATION} с" || echo "полный bag")"
  demo_kv "Визуализация" "$(${RVIZ} && echo "RViz + bag" || echo "headless")"
  demo_kv "Start-offset" "$([[ "${START_OFFSET}" != "0" ]] && echo "${START_OFFSET} с" || echo "0")"
  demo_kv "Выход" "${OUT_DIR}"
  echo ""
fi

RVIZ_ARG="rviz_enable:=false"
${RVIZ} && RVIZ_ARG="rviz_enable:=true"

PLAY_FLAGS=(--clock --rate 1.0 --disable-keyboard-controls)
[[ "${START_OFFSET}" != "0" ]] && PLAY_FLAGS+=(--start-offset "${START_OFFSET}")

cleanup() {
  euroc_stop_recorder "${REC_PID:-}"
  if [[ -n "${LAUNCH_PID}" ]] && kill -0 "${LAUNCH_PID}" 2>/dev/null; then
    kill "${LAUNCH_PID}" 2>/dev/null || true
    wait "${LAUNCH_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

launch_openvins() {
  local viz_label=""
  ${RVIZ} && viz_label=" + RViz"
  ${VERBOSE} && demo_step 1 4 "Запуск OpenVINS${viz_label}..."
  # shellcheck disable=SC2086
  ros2 launch "${LAUNCH_FILE}" ${RVIZ_ARG} ${CONFIG_PATH_ARG} > "${OUT_DIR}/openvins.log" 2>&1 &
  LAUNCH_PID=$!
  sleep 8
  euroc_verify_openvins "${LAUNCH_PID}" "${OUT_DIR}/openvins.log"
  ${VERBOSE} && demo_ok "OpenVINS запущен (pid ${LAUNCH_PID})"
}

start_recorder() {
  ${VERBOSE} && demo_step 2 4 "Запись траектории → trajectory_tum.txt"
  REC_PID="$(euroc_start_recorder "${TRAJ_FILE}")"
  sleep 1
  ${VERBOSE} && demo_ok "Recorder запущен (pid ${REC_PID})"
}

play_bag() {
  ${VERBOSE} && demo_step 3 4 "Воспроизведение bag..."
  local play_cmd=(ros2 bag play "${BAG}" "${PLAY_FLAGS[@]}")
  local log_mode="file"
  ${VERBOSE} && ${RVIZ} && log_mode="tee"

  if [[ -n "${DURATION}" ]]; then
    ${VERBOSE} && echo "  ${DURATION} с @ rate 1.0..."
    if [[ "${log_mode}" == "tee" ]]; then
      timeout "${DURATION}" "${play_cmd[@]}" 2>&1 | tee "${OUT_DIR}/bag_play.log" || true
    else
      timeout "${DURATION}" "${play_cmd[@]}" > "${OUT_DIR}/bag_play.log" 2>&1 || true
    fi
  else
    ${VERBOSE} && echo "  полный bag..."
    if [[ "${log_mode}" == "tee" ]]; then
      "${play_cmd[@]}" 2>&1 | tee "${OUT_DIR}/bag_play.log"
    else
      "${play_cmd[@]}" > "${OUT_DIR}/bag_play.log" 2>&1
    fi
  fi
  ${VERBOSE} && demo_ok "Bag воспроизведён"
}

finish() {
  ${VERBOSE} && demo_step 4 4 "Сбор результатов..."
  euroc_stop_recorder "${REC_PID:-}"
  REC_PID=""
  sleep 2

  if ${VERBOSE}; then
    echo ""
    echo "${_C_DIM}--- OpenVINS (последние строки) ---${_C_RESET}"
    euroc_grep_summary "${OUT_DIR}/openvins.log"
    if [[ "${MODE}" == "adaptive" && -f "${TRUST_LOG}" ]]; then
      echo ""
      echo "${_C_DIM}--- Trust (последние строки) ---${_C_RESET}"
      tail -3 "${TRUST_LOG}"
    fi
  fi

  local trust_arg=""
  [[ "${MODE}" == "adaptive" ]] && trust_arg="${TRUST_LOG}"
  euroc_show_final_summary "${MODE}" "${SEQ}" "${OUT_DIR}" "${TRAJ_FILE}" "${trust_arg}" "${EVAL}"
}

launch_openvins
start_recorder
play_bag
finish
