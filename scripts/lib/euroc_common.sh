#!/usr/bin/env bash
# Shared helpers for EuRoC baseline / adaptive experiment runs.
# shellcheck disable=SC2034

EUROC_SEQUENCES=(MH_01_easy MH_04_difficult MH_05_difficult)

declare -A EUROC_START_OFFSET=(
  [MH_01_easy]=40
  [MH_02_easy]=35
  [MH_03_medium]=5
  [MH_04_difficult]=10
  [MH_05_difficult]=5
)

declare -A EUROC_GT_FILE=(
  [MH_04_difficult]="MH_04_difficult.txt"
  [MH_05_difficult]="MH_05_difficult.txt"
)

# ANSI (disabled when not a tty)
if [[ -t 1 ]]; then
  _C_BOLD=$'\033[1m'
  _C_DIM=$'\033[2m'
  _C_GREEN=$'\033[32m'
  _C_YELLOW=$'\033[33m'
  _C_BLUE=$'\033[34m'
  _C_CYAN=$'\033[36m'
  _C_RED=$'\033[31m'
  _C_RESET=$'\033[0m'
else
  _C_BOLD="" _C_DIM="" _C_GREEN="" _C_YELLOW="" _C_BLUE="" _C_CYAN="" _C_RED="" _C_RESET=""
fi

demo_banner() {
  local title="$1"
  echo ""
  echo "${_C_BOLD}${_C_CYAN}════════════════════════════════════════════════════════════${_C_RESET}"
  printf "${_C_BOLD}${_C_CYAN}  %-57s${_C_RESET}\n" "${title}"
  echo "${_C_BOLD}${_C_CYAN}════════════════════════════════════════════════════════════${_C_RESET}"
  echo ""
}

demo_step() {
  local n="$1" total="$2" msg="$3"
  echo "${_C_BOLD}${_C_BLUE}[${n}/${total}]${_C_RESET} ${msg}"
}

demo_kv() {
  printf "  ${_C_DIM}%-14s${_C_RESET} %s\n" "$1" "$2"
}

demo_ok() {
  echo "${_C_GREEN}✓${_C_RESET} $*"
}

demo_warn() {
  echo "${_C_YELLOW}!${_C_RESET} $*"
}

demo_fail() {
  echo "${_C_RED}✗${_C_RESET} $*" >&2
}

euroc_gt_path() {
  local seq="$1"
  local gt_name="${EUROC_GT_FILE[${seq}]:-}"
  [[ -z "${gt_name}" ]] && return 1
  local root
  root="$(aspiranture_root)"
  local gt="${root}/ws_vins/src/open_vins/ov_data/euroc_mav/${gt_name}"
  [[ -f "${gt}" ]] || return 1
  echo "${gt}"
}

euroc_prepare_adaptive_config() {
  local out_dir="$1"
  local trust_log="$2"
  local trust_cfg_dir
  trust_cfg_dir="$(aspiranture_root)/ws_vins/src/open_vins/config/euroc_mav_trust"
  cp "${trust_cfg_dir}/kalibr_imu_chain.yaml" "${out_dir}/"
  cp "${trust_cfg_dir}/kalibr_imucam_chain.yaml" "${out_dir}/"
  sed "s|trust_log_filepath:.*|trust_log_filepath: \"${trust_log}\"|" \
    "${trust_cfg_dir}/estimator_config.yaml" > "${out_dir}/estimator_config.yaml"
  echo "${out_dir}/estimator_config.yaml"
}

euroc_verify_openvins() {
  local launch_pid="$1"
  local log_file="$2"
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    demo_fail "OpenVINS завершился раньше времени"
    tail -30 "${log_file}" >&2
    return 1
  fi
  if grep -q "process has died" "${log_file}" 2>/dev/null; then
    demo_fail "OpenVINS упал — см. лог"
    tail -20 "${log_file}" >&2
    return 1
  fi
  return 0
}

euroc_start_recorder() {
  local traj_file="$1"
  python3 "$(aspiranture_root)/scripts/record_trajectory.py" \
    --output "${traj_file}" \
    --ros-args -p use_sim_time:=true \
    > "${traj_file%.txt}_recorder.log" 2>&1 &
  echo $!
}

euroc_stop_recorder() {
  local rec_pid="$1"
  if [[ -n "${rec_pid}" ]] && kill -0 "${rec_pid}" 2>/dev/null; then
    kill "${rec_pid}" 2>/dev/null || true
    wait "${rec_pid}" 2>/dev/null || true
  fi
}

euroc_grep_summary() {
  local log_file="$1"
  local pattern="${2:-subscribing|init|TIME|trust|failed|error|died|successful}"
  grep -aE "${pattern}" "${log_file}" | tail -25 || tail -15 "${log_file}"
}

euroc_traj_stats() {
  local traj_file="$1"
  if [[ ! -f "${traj_file}" ]]; then
    demo_warn "Файл траектории не создан: ${traj_file}"
    return 1
  fi
  local n
  n=$(grep -cv '^#' "${traj_file}" || true)
  if [[ "${n}" -lt 2 ]]; then
    demo_warn "Мало точек в траектории (${n})"
    return 1
  fi
  demo_ok "Траектория: ${traj_file} (${n} poses, формат TUM)"
  return 0
}

euroc_eval_ate() {
  local traj_file="$1"
  local seq="$2"
  local out_dir="$3"
  local gt
  gt="$(euroc_gt_path "${seq}" || true)"
  if [[ -z "${gt}" ]]; then
    demo_warn "Ground truth для ${seq} недоступен — ATE пропущен"
    return 0
  fi
  demo_step "·" "·" "Расчёт ATE/RPE (evo)..."
  source_venv
  if python3 "$(aspiranture_root)/scripts/evaluate_trajectory.py" \
      --est "${traj_file}" --gt "${gt}" --out-dir "${out_dir}/metrics" 2>&1 | tee "${out_dir}/metrics/eval.log"; then
    demo_ok "Метрики: ${out_dir}/metrics/"
  else
    demo_warn "Оценка траектории не удалась (нужен venv + evo)"
  fi
}

euroc_show_final_summary() {
  local mode="$1"
  local seq="$2"
  local out_dir="$3"
  local traj_file="$4"
  local trust_log="${5:-}"
  local do_eval="${6:-false}"

  echo ""
  echo "${_C_BOLD}── Итоги прогона ──${_C_RESET}"
  demo_kv "Режим" "${mode}"
  demo_kv "Последов." "${seq}"
  demo_kv "Результаты" "${out_dir}"
  echo ""

  if [[ -f "${out_dir}/openvins.log" ]]; then
    if grep -aq "successful initialization" "${out_dir}/openvins.log"; then
      demo_ok "Инициализация VIO успешна"
    else
      demo_warn "Инициализация не подтверждена в логе"
    fi
  fi

  euroc_traj_stats "${traj_file}" || true

  if [[ -n "${trust_log}" && -f "${trust_log}" ]]; then
    local n_trust mean_c
    n_trust=$(($(wc -l < "${trust_log}") - 1))
    mean_c=$(awk -F, 'NR>1 {s+=$6; n++} END {if(n>0) printf "%.3f", s/n; else print "n/a"}' "${trust_log}")
    demo_ok "Trust log: ${trust_log} (${n_trust} записей, mean c≈${mean_c})"
  fi

  if [[ "${do_eval}" == "true" ]]; then
    euroc_eval_ate "${traj_file}" "${seq}" "${out_dir}" || true
  fi

  echo ""
  echo "${_C_DIM}Подробный лог OpenVINS:${_C_RESET} ${out_dir}/openvins.log"
  if [[ "${mode}" == "adaptive" ]]; then
    echo "${_C_DIM}Колонки trust_log:${_C_RESET} timestamp,f1,f2,f3,f4,c,n_inliers,..."
  fi
  echo ""
}
