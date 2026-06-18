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
DEGRADE=""
START_OFFSET=""
TRUST_TAU=""
RVIZ=false
EVAL=false
VERBOSE=true
MAX_RETRIES="${EUROC_MAX_RETRIES:-3}"
LAUNCH_PID=""
REC_PID=""
BAG_PID=""

usage() {
  cat <<'EOF'
Usage: run_euroc.sh <baseline|adaptive> [SEQUENCE] [OPTIONS]

Sequences (downloaded):
  MH_01_easy, MH_04_difficult, MH_05_difficult

Options:
  --duration SEC   Playback length in seconds (default: full bag)
  --degrade SPEC   Degrade images: TYPE:LEVEL (e.g. gaussian:5, brightness:40)
  --start-offset S Start bag playback at S seconds (default: from config/datasets.yaml)
  --trust-tau T    Override trust_tau for adaptive (default: 5.0 from config)
  --viz            Open RViz + auto-play bag (single terminal)
  --eval           Compute ATE/RPE after run (needs GT + evo)
  --quiet          Less console output
  --retries N      Re-run on diverged trajectory (default: 3)
  --help           This help

Degradation presets (experiment D1/D3):
  gaussian:5       D1 blur σ=5
  brightness:40    D3 overexposure +40%

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
    --degrade)
      DEGRADE="${2:-}"
      shift 2
      ;;
    --start-offset)
      START_OFFSET="${2:-0}"
      shift 2
      ;;
    --trust-tau)
      TRUST_TAU="${2:-}"
      shift 2
      ;;
    --viz) RVIZ=true; shift ;;
    --eval) EVAL=true; shift ;;
    --quiet) VERBOSE=false; shift ;;
    --retries)
      MAX_RETRIES="${2:-2}"
      shift 2
      ;;
    --help|-h) usage; exit 0 ;;
    -*) echo "Unknown option: $1" >&2; exit 1 ;;
    *)
      if [[ -z "${SEQ}" ]]; then SEQ="$1"; else echo "Unexpected arg: $1" >&2; exit 1; fi
      shift
      ;;
  esac
done

SEQ="${SEQ:-MH_01_easy}"
if [[ -z "${START_OFFSET}" ]]; then
  START_OFFSET="$(euroc_seq_start_offset "${SEQ}")"
fi

source_ros
require_ws_built
euroc_kill_stale_ros

DATA_ROOT="${DATA_ROOT:-$(aspiranture_root)/datasets}"
BAG="$(euroc_resolve_bag "${SEQ}" "${DEGRADE}")" || exit 1
TAG="${MODE}"
if [[ -n "${DEGRADE}" ]]; then
  TAG="${MODE}_$(echo "${DEGRADE}" | tr ':' '_')"
fi
OUT_DIR_BASE="${DATA_ROOT}/results/${SEQ}_${TAG}_$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${OUT_DIR_BASE}"
mkdir -p "${OUT_DIR}"

TRAJ_FILE="${OUT_DIR}/trajectory_tum.txt"
TRUST_LOG="${OUT_DIR}/trust_log.csv"

if [[ "${MODE}" == "baseline" ]]; then
  LAUNCH_FILE="$(aspiranture_root)/launch/euroc_baseline.launch.py"
  CONFIG_PATH_ARG=""
  MODE_LABEL="Baseline (классический OpenVINS, фиксированный шум измерений)"
else
  LAUNCH_FILE="$(aspiranture_root)/launch/euroc_adaptive.launch.py"
  RUN_CONFIG="$(euroc_prepare_adaptive_config "${OUT_DIR}" "${TRUST_LOG}" "${TRUST_TAU}")"
  CONFIG_PATH_ARG="config_path:=${RUN_CONFIG}"
  MODE_LABEL="Adaptive (OpenVINS + trust_estimator, адаптивная ковариация)"
fi

if [[ ! -d "${BAG}" ]]; then
  demo_fail "Bag не найден: ${BAG}"
  echo "  Скачайте: bash scripts/download_datasets.sh minimal --ros2" >&2
  exit 1
fi

DEGRADE_LABEL="нет (чистый bag)"
if [[ -n "${DEGRADE}" ]]; then
  DEGRADE_LABEL="${DEGRADE}"
fi

if ${RVIZ} && [[ -z "${DISPLAY:-}" ]]; then
  demo_warn "DISPLAY не задан — RViz может не открыться"
fi

if ${VERBOSE}; then
  demo_banner "Прогон EuRoC — ${MODE}"
  demo_kv "Режим" "${MODE_LABEL}"
  demo_kv "Последов." "${SEQ}"
  demo_kv "Bag" "${BAG}"
  demo_kv "Деградация" "${DEGRADE_LABEL}"
  demo_kv "Длительность" "$([[ -n "${DURATION}" ]] && echo "${DURATION} с" || echo "полный bag")"
  demo_kv "Визуализация" "$(${RVIZ} && echo "RViz + bag" || echo "headless")"
  demo_kv "Start-offset" "$([[ "${START_OFFSET}" != "0" ]] && echo "${START_OFFSET} с" || echo "0")"
  demo_kv "Повторы" "до ${MAX_RETRIES}× при расхождении"
  demo_kv "Выход" "${OUT_DIR_BASE}"
  echo ""
fi

RVIZ_ARG="rviz_enable:=false"
${RVIZ} && RVIZ_ARG="rviz_enable:=true"

PLAY_FLAGS=(--clock --rate 1.0 --disable-keyboard-controls -d 1)
[[ "${START_OFFSET}" != "0" ]] && PLAY_FLAGS+=(--start-offset "${START_OFFSET}")

stop_bag() {
  if [[ -n "${BAG_PID:-}" ]] && kill -0 "${BAG_PID}" 2>/dev/null; then
    kill "${BAG_PID}" 2>/dev/null || true
    wait "${BAG_PID}" 2>/dev/null || true
  fi
  BAG_PID=""
}

cleanup() {
  euroc_stop_recorder "${REC_PID:-}"
  stop_bag
  if [[ -n "${LAUNCH_PID}" ]] && kill -0 "${LAUNCH_PID}" 2>/dev/null; then
    kill "${LAUNCH_PID}" 2>/dev/null || true
    wait "${LAUNCH_PID}" 2>/dev/null || true
  fi
  LAUNCH_PID=""
  REC_PID=""
  euroc_kill_stale_ros
}
trap cleanup EXIT INT TERM

launch_openvins() {
  local viz_label=""
  ${RVIZ} && viz_label=" + RViz"
  ${VERBOSE} && demo_step 1 3 "Запуск OpenVINS${viz_label}..."
  : > "${OUT_DIR}/openvins.log"
  # shellcheck disable=SC2086
  ros2 launch "${LAUNCH_FILE}" ${RVIZ_ARG} ${CONFIG_PATH_ARG} >> "${OUT_DIR}/openvins.log" 2>&1 &
  LAUNCH_PID=$!
  if ! euroc_wait_openvins_ready "${OUT_DIR}/openvins.log" 30; then
    demo_warn "OpenVINS не подписался на топики за 30 с — продолжаем"
    sleep 3
  fi
  euroc_verify_openvins "${LAUNCH_PID}" "${OUT_DIR}/openvins.log"
  sleep 2
  ${VERBOSE} && demo_ok "OpenVINS запущен (pid ${LAUNCH_PID})"
}

play_bag() {
  ${VERBOSE} && demo_step 2 3 "Воспроизведение bag + запись траектории..."
  local play_cmd=(ros2 bag play "${BAG}" "${PLAY_FLAGS[@]}")
  local log_mode="file"
  ${VERBOSE} && ${RVIZ} && log_mode="tee"

  if [[ -n "${DURATION}" ]]; then
    play_cmd+=(--playback-duration "${DURATION}")
    ${VERBOSE} && echo "  ${DURATION} с @ rate 1.0 (delay 1 с)..."
  else
    ${VERBOSE} && echo "  полный bag @ rate 1.0 (delay 1 с)..."
  fi

  if [[ "${log_mode}" == "tee" ]]; then
    "${play_cmd[@]}" 2>&1 | tee "${OUT_DIR}/bag_play.log" &
  else
    "${play_cmd[@]}" > "${OUT_DIR}/bag_play.log" 2>&1 &
  fi
  BAG_PID=$!

  ${VERBOSE} && echo "  ожидание инициализации VIO..."
  if euroc_wait_vio_init "${OUT_DIR}/openvins.log" 45; then
    ${VERBOSE} && demo_ok "Инициализация VIO — запись траектории"
    sleep 3
  else
    demo_warn "Init не подтверждён за 45 с — запись с текущего момента"
  fi

  REC_PID="$(euroc_start_recorder "${TRAJ_FILE}")"
  ${VERBOSE} && demo_ok "Recorder запущен (pid ${REC_PID})"

  wait "${BAG_PID}" 2>/dev/null || true
  BAG_PID=""
  demo_reset
  ${VERBOSE} && demo_ok "Bag воспроизведён"
}

finish() {
  ${VERBOSE} && demo_step 3 3 "Сбор результатов..."
  euroc_stop_recorder "${REC_PID:-}"
  REC_PID=""
  sleep 2

  if ${VERBOSE}; then
    echo ""
    demo_heading "--- OpenVINS (последние строки) ---"
    euroc_grep_summary "${OUT_DIR}/openvins.log"
    if [[ "${MODE}" == "adaptive" && -f "${TRUST_LOG}" ]]; then
      demo_trust_block "${TRUST_LOG}"
    fi
  fi

  local trust_arg=""
  [[ "${MODE}" == "adaptive" ]] && trust_arg="${TRUST_LOG}"
  export EUROC_RUN_START_OFFSET="${START_OFFSET}"
  euroc_show_final_summary "${MODE}" "${SEQ}" "${OUT_DIR}" "${TRAJ_FILE}" "${trust_arg}" "${EVAL}"

  local retry_n=0 trust_tau_args=()
  if [[ "${OUT_DIR}" =~ _retry([0-9]+)$ ]]; then
    retry_n="${BASH_REMATCH[1]}"
  fi
  if [[ -n "${TRUST_TAU}" ]]; then
    trust_tau_args=(--trust-tau "${TRUST_TAU}")
  fi
  python3 "$(aspiranture_root)/scripts/lib/run_results.py" write-meta \
    --dir "${OUT_DIR}" \
    --seq "${SEQ}" \
    --mode "${MODE}" \
    --degrade "${DEGRADE}" \
    --start-offset "${START_OFFSET}" \
    "${trust_tau_args[@]}" \
    --retry "${retry_n}" \
    >/dev/null 2>&1 || true

  echo "RESULT_DIR=${OUT_DIR}"
}

run_once() {
  launch_openvins
  play_bag
  finish
  euroc_traj_is_healthy "${TRAJ_FILE}"
}

attempt=1
while [[ "${attempt}" -le "${MAX_RETRIES}" ]]; do
  if [[ "${attempt}" -gt 1 ]]; then
    cleanup
    OUT_DIR="${OUT_DIR_BASE}_retry${attempt}"
    mkdir -p "${OUT_DIR}"
    TRAJ_FILE="${OUT_DIR}/trajectory_tum.txt"
    TRUST_LOG="${OUT_DIR}/trust_log.csv"
    if [[ "${MODE}" == "adaptive" ]]; then
      RUN_CONFIG="$(euroc_prepare_adaptive_config "${OUT_DIR}" "${TRUST_LOG}" "${TRUST_TAU}")"
      CONFIG_PATH_ARG="config_path:=${RUN_CONFIG}"
    fi
    demo_warn "Повтор ${attempt}/${MAX_RETRIES} — предыдущий прогон расходился"
    ${VERBOSE} && demo_kv "Новый выход" "${OUT_DIR}"
    echo ""
  else
    OUT_DIR="${OUT_DIR_BASE}"
  fi

  if run_once; then
    break
  fi

  if [[ "${attempt}" -ge "${MAX_RETRIES}" ]]; then
    demo_warn "Все ${MAX_RETRIES} попытки завершились расхождением траектории"
    break
  fi
  attempt=$((attempt + 1))
done
