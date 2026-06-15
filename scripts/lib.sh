#!/usr/bin/env bash
# Shared helpers for experiment scripts.
# shellcheck disable=SC2034

aspiranture_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# ROS setup.bash references unset vars; must not run under `set -u`.
source_ros() {
  set +u
  # shellcheck source=/dev/null
  source /opt/ros/jazzy/setup.bash
  local root
  root="$(aspiranture_root)"
  if [[ -f "${root}/ws_vins/install/setup.bash" ]]; then
    # shellcheck source=/dev/null
    source "${root}/ws_vins/install/setup.bash"
  fi
  set -u
}

source_venv() {
  local root
  root="$(aspiranture_root)"
  if [[ -f "${root}/venv/bin/activate" ]]; then
    # shellcheck source=/dev/null
    source "${root}/venv/bin/activate"
  fi
}

require_ws_built() {
  if ! ros2 pkg prefix ov_msckf &>/dev/null; then
    echo "ERROR: ov_msckf not found. Build workspace first:" >&2
    echo "  source /opt/ros/jazzy/setup.bash && cd ws_vins && colcon build --symlink-install" >&2
    return 1
  fi
}
