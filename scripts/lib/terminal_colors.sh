#!/usr/bin/env bash
# Shared ANSI palette for demo / EuRoC scripts.
# Enable when stdout is a tty, or DEMO_COLOR/FORCE_COLOR is set (piped from run_demo.py).

_terminal_colors_enabled() {
  [[ -z "${NO_COLOR:-}" ]] && { [[ -t 1 ]] || [[ -n "${DEMO_COLOR:-}" ]] || [[ -n "${FORCE_COLOR:-}" ]]; }
}

if _terminal_colors_enabled; then
  _C_RESET=$'\033[0m'
  _C_BOLD=$'\033[1m'
  _C_DIM=$'\033[2m'
  _C_WHITE=$'\033[1;37m'      # section headings
  _C_BLUE=$'\033[94m'          # banner frames (bright blue)
  _C_CYAN=$'\033[96m'          # menu / step numbers (bright cyan)
  _C_GREEN=$'\033[32m'
  _C_YELLOW=$'\033[33m'
  _C_MAGENTA=$'\033[35m'
  _C_RED=$'\033[31m'
else
  _C_RESET="" _C_BOLD="" _C_DIM="" _C_WHITE="" _C_BLUE="" _C_CYAN=""
  _C_GREEN="" _C_YELLOW="" _C_MAGENTA="" _C_RED=""
fi

# Reset terminal attributes after external tools (ros2, grep via pipe, etc.)
demo_reset() {
  if _terminal_colors_enabled; then
    printf '%b' "${_C_RESET}"
  fi
}
