#!/usr/bin/env bash
# Shared helpers for EuRoC baseline / adaptive experiment runs.
# shellcheck disable=SC2034

# shellcheck source=terminal_colors.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/terminal_colors.sh"

_REGISTRY_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/datasets_registry.py"

# Метаданные последовательности из config/datasets.yaml (+ datasets_custom.yaml)
euroc_registry_query() {
  local seq="$1"
  local key="$2"
  python3 "${_REGISTRY_PY}" query "${seq}" "${key}" 2>/dev/null || true
}

euroc_seq_start_offset() {
  local seq="$1"
  local v
  v="$(euroc_registry_query "${seq}" start_offset)"
  echo "${v:-0}"
}

euroc_seq_expected_path_m() {
  local seq="$1"
  euroc_registry_query "${seq}" expected_path_m
}

demo_banner() {
  local title="$1"
  echo ""
  echo "${_C_BLUE}════════════════════════════════════════════════════════════${_C_RESET}"
  printf "  ${_C_WHITE}%s${_C_RESET}\n" "${title}"
  echo "${_C_BLUE}════════════════════════════════════════════════════════════${_C_RESET}"
  echo ""
}

demo_heading() {
  echo "${_C_WHITE}$*${_C_RESET}"
}

demo_step() {
  local n="$1" total="$2" msg="$3"
  echo "${_C_CYAN}[${n}/${total}]${_C_RESET} ${msg}"
}

demo_kv() {
  printf "  ${_C_DIM}%-14s${_C_RESET} %s\n" "$1" "$2"
}

demo_section() {
  echo "${_C_WHITE}$*${_C_RESET}"
}

demo_trust_block() {
  echo ""
  echo "${_C_MAGENTA}--- Trust (последние строки) ---${_C_RESET}"
  tail -3 "$1"
  demo_reset
}

demo_metric_ok() {
  printf '%b✓%b %b%s%b\n' "${_C_GREEN}" "${_C_RESET}" "${_C_GREEN}${_C_BOLD}" "$*" "${_C_RESET}"
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

euroc_degraded_cache_path() {
  local seq="$1"
  local dtype="$2"
  local level="$3"
  local level_tag="${level//./p}"
  local root
  root="$(aspiranture_root)"
  echo "${root}/datasets/euroc/degraded/${seq}_${dtype}${level_tag}_ros2"
}

euroc_resolve_bag() {
  local seq="$1"
  local degrade_spec="${2:-}"
  local base
  base="$(euroc_registry_query "${seq}" bag_path)"
  if [[ -z "${base}" ]]; then
    local data_root="${DATA_ROOT:-$(aspiranture_root)/datasets}"
    base="${data_root}/euroc/${seq}_ros2"
  fi

  if [[ -z "${degrade_spec}" ]]; then
    echo "${base}"
    return 0
  fi

  local dtype="${degrade_spec%%:*}"
  local dlevel="${degrade_spec#*:}"
  local out
  out="$(euroc_degraded_cache_path "${seq}" "${dtype}" "${dlevel}")"

  if [[ -d "${out}" ]] && compgen -G "${out}/*.db3" > /dev/null; then
    echo "${out}"
    return 0
  fi

  if [[ ! -d "${base}" ]]; then
    demo_fail "Исходный bag не найден: ${base}" >&2
    return 1
  fi

  demo_section "Подготовка деградированного bag (${dtype}, level=${dlevel})..." >&2
  source_venv
  if ! python3 "$(aspiranture_root)/scripts/degrade_ros2_bag.py" \
      --input "${base}" --output "${out}" \
      --type "${dtype}" --level "${dlevel}" >&2; then
    demo_fail "Не удалось создать деградированный bag" >&2
    return 1
  fi
  demo_ok "Деградированный bag: ${out}" >&2
  echo "${out}"
}

euroc_gt_path() {
  local seq="$1"
  local gt
  gt="$(euroc_registry_query "${seq}" gt_path)"
  [[ -n "${gt}" && -f "${gt}" ]] || return 1
  echo "${gt}"
}

euroc_prepare_adaptive_config() {
  local out_dir="$1"
  local trust_log="$2"
  local trust_tau="${3:-}"
  local trust_cfg_dir
  trust_cfg_dir="$(aspiranture_root)/ws_vins/src/open_vins/config/euroc_mav_trust"
  cp "${trust_cfg_dir}/kalibr_imu_chain.yaml" "${out_dir}/"
  cp "${trust_cfg_dir}/kalibr_imucam_chain.yaml" "${out_dir}/"
  sed "s|trust_log_filepath:.*|trust_log_filepath: \"${trust_log}\"|" \
    "${trust_cfg_dir}/estimator_config.yaml" > "${out_dir}/estimator_config.yaml"
  if [[ -n "${trust_tau}" ]]; then
    sed -i "s|^trust_tau:.*|trust_tau: ${trust_tau}|" "${out_dir}/estimator_config.yaml"
  fi
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

euroc_kill_stale_ros() {
  # Остаточные ноды после compare/прерванного прогона ломают следующий запуск.
  pkill -f "run_subscribe_msckf" 2>/dev/null || true
  pkill -f "trajectory_recorder" 2>/dev/null || true
  pkill -f "ros2 bag play" 2>/dev/null || true
  pkill -f "ros2 launch.*euroc_" 2>/dev/null || true
  pkill -f "rviz2" 2>/dev/null || true
  sleep 3
}

# Ждёт появления строки в логе (poll раз в секунду).
euroc_wait_log_pattern() {
  local log_file="$1"
  local pattern="$2"
  local timeout="${3:-30}"
  local elapsed=0
  while [[ "${elapsed}" -lt "${timeout}" ]]; do
    if [[ -f "${log_file}" ]] && grep -aqE "${pattern}" "${log_file}" 2>/dev/null; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

euroc_wait_openvins_ready() {
  local log_file="$1"
  local timeout="${2:-30}"
  euroc_wait_log_pattern "${log_file}" "subscribing to IMU" "${timeout}"
}

euroc_wait_vio_init() {
  local log_file="$1"
  local timeout="${2:-45}"
  euroc_wait_log_pattern "${log_file}" "successful initialization" "${timeout}"
}

# 0 = ok, 1 = diverged / missing
euroc_traj_is_healthy() {
  local traj_file="$1"
  [[ -f "${traj_file}" ]] || return 1
  local stats
  stats="$(python3 "$(aspiranture_root)/scripts/traj_stats.py" "${traj_file}" 2>/dev/null || true)"
  [[ -n "${stats}" ]] || return 1
  [[ "$(echo "${stats}" | sed -n 's/.*diverged=\([0-9]*\).*/\1/p')" == "0" ]]
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
  demo_reset
  grep -aE "${pattern}" "${log_file}" | tail -25 || tail -15 "${log_file}"
  demo_reset
  printf '\n'
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
  local metrics_dir="${out_dir}/metrics"
  mkdir -p "${metrics_dir}"
  if python3 "$(aspiranture_root)/scripts/evaluate_trajectory.py" \
      --est "${traj_file}" --gt "${gt}" --out-dir "${metrics_dir}" \
      > "${metrics_dir}/eval.log" 2>&1; then
    if [[ -f "${metrics_dir}/summary.txt" ]]; then
      # shellcheck disable=SC1090
      source "${metrics_dir}/summary.txt"
      demo_metric_ok "ATE (APE RMSE): ${ape_rmse_m:-?} m | RPE RMSE: ${rpe_rmse_m:-?} m"
      demo_kv "Метрики" "${metrics_dir}/"
    else
      demo_ok "Метрики сохранены: ${metrics_dir}/"
    fi
  else
    demo_warn "Оценка траектории не удалась — см. ${metrics_dir}/eval.log"
    tail -5 "${metrics_dir}/eval.log" 2>/dev/null || true
    return 1
  fi
}

euroc_traj_health() {
  local traj_file="$1"
  local seq="${2:-}"
  local stats
  stats="$(python3 "$(aspiranture_root)/scripts/traj_stats.py" "${traj_file}" 2>/dev/null || true)"
  [[ -z "${stats}" ]] && return 0
  local poses path_m span_m diverged max_coord max_jump expected
  poses=$(echo "${stats}" | sed -n 's/.*poses=\([0-9]*\).*/\1/p')
  path_m=$(echo "${stats}" | sed -n 's/.*path_m=\([0-9.]*\).*/\1/p')
  span_m=$(echo "${stats}" | sed -n 's/.*span_m=\([0-9.]*\).*/\1/p')
  diverged=$(echo "${stats}" | sed -n 's/.*diverged=\([0-9]*\).*/\1/p')
  max_coord=$(echo "${stats}" | sed -n 's/.*max_coord_m=\([0-9.]*\).*/\1/p')
  max_jump=$(echo "${stats}" | sed -n 's/.*max_jump_m=\([0-9.]*\).*/\1/p')
  expected="$(euroc_seq_expected_path_m "${seq}")"

  demo_kv "Длина пути" "~${path_m} m (сумма шагов, ${poses} poses)"
  demo_kv "Span start→end" "~${span_m} m (не путать с длиной пути)"
  if [[ -n "${expected}" ]]; then
    demo_kv "Ожидаемо (GT)" "~${expected} m по ground truth"
    if [[ "${diverged}" != "1" ]]; then
      local hi
      hi="$(python3 - <<PY
exp = float("${expected}")
path = float("${path_m}")
if path > exp * 1.5:
    print("high")
elif path < exp * 0.4:
    print("low")
PY
)"
      if [[ "${hi}" == "high" ]]; then
        demo_warn "Длина пути >> GT — вероятен drift/jitter фильтра (max скачок ${max_jump} m)"
      elif [[ "${hi}" == "low" ]]; then
        demo_warn "Длина пути << GT — возможно короткий bag или нет init"
      fi
    fi
  fi
  if [[ "${diverged}" == "1" ]]; then
    demo_warn "Траектория расходится (max координата ${max_coord} m) — ATE некорректен, прогон браковать"
    return 1
  fi
  return 0
}

euroc_read_metric() {
  local summary_file="$1"
  local key="$2"
  [[ -f "${summary_file}" ]] || return 1
  sed -n "s/^${key}=//p" "${summary_file}" | head -1
}

euroc_print_compare_table() {
  local seq="$1"
  local baseline_dir="$2"
  local adaptive_dir="$3"
  local degraded="${4:-false}"
  local b_ape a_ape b_rpe a_rpe

  echo ""
  if [[ "${degraded}" == "true" ]]; then
    demo_heading "── Сравнение baseline vs adaptive (${seq}, деградированный bag) ──"
  else
    demo_heading "── Сравнение baseline vs adaptive (${seq}, чистый bag) ──"
  fi
  printf "  %-12s ${_C_YELLOW}%12s${_C_RESET} ${_C_GREEN}%12s${_C_RESET}\n" "" "Baseline" "Adaptive"

  b_ape="$(euroc_read_metric "${baseline_dir}/metrics/summary.txt" "ape_rmse_m" || echo "n/a")"
  a_ape="$(euroc_read_metric "${adaptive_dir}/metrics/summary.txt" "ape_rmse_m" || echo "n/a")"
  b_rpe="$(euroc_read_metric "${baseline_dir}/metrics/summary.txt" "rpe_rmse_m" || echo "n/a")"
  a_rpe="$(euroc_read_metric "${adaptive_dir}/metrics/summary.txt" "rpe_rmse_m" || echo "n/a")"

  printf "  %-12s ${_C_YELLOW}%12s${_C_RESET} ${_C_GREEN}%12s${_C_RESET}\n" "APE RMSE [m]" "${b_ape}" "${a_ape}"
  printf "  %-12s ${_C_YELLOW}%12s${_C_RESET} ${_C_GREEN}%12s${_C_RESET}\n" "RPE RMSE [m]" "${b_rpe}" "${a_rpe}"
  echo ""

  if [[ "${b_ape}" != "n/a" && "${a_ape}" != "n/a" ]]; then
    local verdict
    verdict="$(python3 - <<PY
b, a = float("${b_ape}"), float("${a_ape}")
degraded = "${degraded}" == "true"
if degraded:
    if a < b * 0.9:
        print("confirmed")
    elif a <= b * 1.05:
        print("neutral")
    else:
        pct = (a / b - 1) * 100 if b > 0 else 0
        print(f"worse:{pct:.0f}")
else:
    if a <= b * 1.05 and a >= b * 0.95:
        print("similar")
    elif a < b * 0.9:
        print("unexpected_better")
    elif a > b * 1.05:
        pct = (a / b - 1) * 100 if b > 0 else 0
        print(f"worse:{pct:.0f}")
    else:
        print("similar")
PY
)"
    case "${verdict}" in
      confirmed)
        demo_ok "Гипотеза подтверждена: adaptive лучше на деградированных данных (ATE ↓ >10%)"
        ;;
      neutral)
        demo_warn "На деградации разница <10% — нужны другие уровни или сценарии"
        ;;
      similar)
        echo "  ${_C_GREEN}→${_C_RESET} На чистых данных adaptive ≈ baseline (в пределах 5%) — ожидаемо."
        ;;
      unexpected_better)
        demo_warn "На чистых данных adaptive заметно лучше baseline — проверьте на деградации (blur/засветка)"
        ;;
      worse:*)
        if [[ "${degraded}" == "true" ]]; then
          demo_fail "Adaptive хуже на ${verdict#worse:}% — гипотеза НЕ подтверждена"
        else
          demo_warn "Adaptive хуже на ${verdict#worse:}% на чистых данных"
        fi
        ;;
    esac
    if [[ "${degraded}" != "true" ]]; then
      echo "  ${_C_DIM}Для проверки гипотезы запустите сценарий с деградацией (меню «Деградированный bag»).${_C_RESET}"
    fi
  fi
  echo ""
  demo_kv "Baseline" "${baseline_dir}"
  demo_kv "Adaptive" "${adaptive_dir}"
  echo ""
}

euroc_show_final_summary() {
  local mode="$1"
  local seq="$2"
  local out_dir="$3"
  local traj_file="$4"
  local trust_log="${5:-}"
  local do_eval="${6:-false}"

  echo ""
  demo_heading "── Итоги прогона ──"
  if [[ "${mode}" == "baseline" ]]; then
    printf "  ${_C_DIM}%-14s${_C_RESET} ${_C_YELLOW}%s${_C_RESET}\n" "Режим" "${mode}"
  else
    printf "  ${_C_DIM}%-14s${_C_RESET} ${_C_GREEN}%s${_C_RESET}\n" "Режим" "${mode}"
  fi
  demo_kv "Последов." "${seq}"
  demo_kv "Результаты" "${out_dir}"
  echo ""

  if [[ -f "${out_dir}/openvins.log" ]]; then
    if grep -aq "successful initialization" "${out_dir}/openvins.log"; then
      local init_disp d0 d1 offset="${EUROC_RUN_START_OFFSET:-}"
      init_disp=$(grep -a "disparity is" "${out_dir}/openvins.log" | grep -B0 -a "successful initialization" 2>/dev/null | head -1 || true)
      if [[ -z "${init_disp}" ]]; then
        init_disp=$(grep -a "successful initialization" -B1 "${out_dir}/openvins.log" | grep "disparity is" | tail -1 || true)
      fi
      d0=$(echo "${init_disp}" | sed -n 's/.*disparity is \([0-9.]*\),.*/\1/p')
      d1=$(echo "${init_disp}" | sed -n 's/.*disparity is [0-9.]*,\([0-9.]*\).*/\1/p')
      if [[ -n "${d0}" && -n "${d1}" ]] && awk -v a="${d0}" -v b="${d1}" 'BEGIN{exit !(a+0>20 || b+0>20)}'; then
        demo_warn "Init при движении (disparity ${d0}, ${d1}) — для ${seq} нужен start-offset (сейчас: ${offset:-?} с)"
      else
        demo_ok "Инициализация VIO успешна"
      fi
    else
      demo_warn "Инициализация не подтверждена в логе"
    fi
  fi

  euroc_traj_stats "${traj_file}" || true
  local traj_ok=true
  euroc_traj_health "${traj_file}" "${seq}" || traj_ok=false

  if [[ -n "${trust_log}" && -f "${trust_log}" ]]; then
    local n_trust mean_c
    n_trust=$(($(wc -l < "${trust_log}") - 1))
    mean_c=$(awk -F, 'NR>1 {s+=$6; n++} END {if(n>0) printf "%.3f", s/n; else print "n/a"}' "${trust_log}")
    printf '%b✓%b Trust log: %b%s%b (%s записей, mean c≈%s)\n' \
      "${_C_GREEN}" "${_C_RESET}" "${_C_MAGENTA}" "${trust_log}" "${_C_RESET}" \
      "${n_trust}" "${mean_c}"
  fi

  if [[ "${do_eval}" == "true" ]]; then
    if [[ "${traj_ok}" == "true" ]]; then
      euroc_eval_ate "${traj_file}" "${seq}" "${out_dir}" || true
    else
      demo_warn "ATE/RPE пропущен — траектория расходится, метрики некорректны"
    fi
  fi

  echo ""
  echo "${_C_DIM}Подробный лог OpenVINS:${_C_RESET} ${out_dir}/openvins.log"
  if [[ "${mode}" == "adaptive" ]]; then
    echo "${_C_DIM}Колонки trust_log:${_C_RESET} timestamp,f1,f2,f3,f4,c,n_inliers,..."
  fi
  echo ""
}
