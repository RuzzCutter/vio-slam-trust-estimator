#!/usr/bin/env bash
# Download EuRoC datasets for OpenVINS on ROS 2 Jazzy.
#
# Usage:
#   bash download_datasets.sh minimal --ros2
#   bash download_datasets.sh --seq MH_04_difficult --seq MH_05_difficult --ros2
#   bash download_datasets.sh --seq MH_02_easy --source gdrive --ros2
#   bash scripts/lib/datasets_registry.py list
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

MODE="minimal"
DO_ROS2=true
EUROC_SOURCE="${EUROC_SOURCE:-ethz-rc}"
REQUESTED_SEQS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    minimal|full) MODE="$1" ;;
    --ros1-only) DO_ROS2=false ;;
    --ros2) DO_ROS2=true ;;
    --seq)
      REQUESTED_SEQS+=("${2:-}")
      shift
      ;;
    --source|--ethz-rc)
      [[ "$1" == "--ethz-rc" ]] && EUROC_SOURCE="ethz-rc" || EUROC_SOURCE="${2:-ethz-rc}"
      [[ "$1" == "--source" ]] && shift
      ;;
    --gdrive) EUROC_SOURCE="gdrive" ;;
    --ethz-legacy) EUROC_SOURCE="ethz-legacy" ;;
    --list)
      exec python3 "${SCRIPT_DIR}/lib/datasets_registry.py" list
      ;;
    --help|-h)
      cat <<'EOF'
Usage: download_datasets.sh [minimal|full] [OPTIONS]

Options:
  --seq ID         Download only this sequence (repeatable)
  --source SRC     ethz-rc | gdrive | ethz-legacy  (default: ethz-rc)
  --ros2           Convert / use ROS2 bags (default)
  --ros1-only      ROS1 .bag only, no conversion
  --list           List catalog sequences and install status
  --help           This help

Examples:
  bash scripts/download_datasets.sh minimal --ros2
  bash scripts/download_datasets.sh --seq MH_04_difficult --ros2
  bash scripts/download_datasets.sh --seq MH_02_easy --source gdrive --ros2
EOF
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      echo "Usage: $0 [minimal|full] [--seq ID ...] [--source SRC] [--ros2|--ros1-only]" >&2
      exit 1
      ;;
  esac
  shift
done

DATA_ROOT="${DATA_ROOT:-$(aspiranture_root)/datasets}"
mkdir -p "${DATA_ROOT}/euroc"

if [[ ${#REQUESTED_SEQS[@]} -gt 0 ]]; then
  SEQS=("${REQUESTED_SEQS[@]}")
else
  case "${MODE}" in
    minimal) SEQS=(MH_01_easy MH_04_difficult MH_05_difficult) ;;
    full)    SEQS=(MH_01_easy MH_02_easy MH_03_medium MH_04_difficult MH_05_difficult) ;;
  esac
fi

# Validate against catalog when PyYAML available
if python3 -c "import yaml" 2>/dev/null; then
  for seq in "${SEQS[@]}"; do
    if ! python3 "${SCRIPT_DIR}/lib/datasets_registry.py" meta "${seq}" start_offset >/dev/null 2>&1; then
      echo "[warn] ${seq} not in config/datasets.yaml — proceeding anyway" >&2
    fi
  done
fi

EUROC_RC_MACHINE_HALL="https://www.research-collection.ethz.ch/server/api/core/bitstreams/7b2419c1-62b5-4714-b7f8-485e5fe3e5fe/content"
MACHINE_HALL_ZIP="${DATA_ROOT}/euroc/machine_hall.zip"

gdrive_id() {
  local seq="$1"
  local id
  id="$(python3 "${SCRIPT_DIR}/lib/datasets_registry.py" meta "${seq}" gdrive_id 2>/dev/null || true)"
  if [[ -n "${id}" && "${id}" != "null" ]]; then
    echo "${id}"
    return 0
  fi
  case "${seq}" in
    MH_01_easy)      echo "1UP4nkuSEOQECZTswwh9BPgfMl-dnDstA" ;;
    MH_02_easy)      echo "1wWZgZCqYz6zzzTXS0iqvQCP-cWfFuGLK" ;;
    MH_03_medium)    echo "1er07gZ8rso8R3Su00hJMm_GZ4z1n9Rpq" ;;
    MH_04_difficult) echo "1eC8joRXo1rh0wzOpq3e-B4dQ8-w6wZYz" ;;
    MH_05_difficult) echo "1zoN94K1Afrp7HXSduRLkJBiEjPKdk1UA" ;;
    *) echo "Unknown sequence: ${seq}" >&2; return 1 ;;
  esac
}

archive_inner_path() {
  local seq="$1"
  local inner
  inner="$(python3 "${SCRIPT_DIR}/lib/datasets_registry.py" meta "${seq}" archive_inner 2>/dev/null || true)"
  if [[ -n "${inner}" && "${inner}" != "null" ]]; then
    echo "${inner}"
  else
    echo "machine_hall/${seq}/${seq}.bag"
  fi
}

download_machine_hall_archive() {
  if [[ -f "${MACHINE_HALL_ZIP}" ]]; then
    echo "[skip] machine_hall.zip ($(du -sh "${MACHINE_HALL_ZIP}" | awk '{print $1}'))"
    return 0
  fi

  echo "[download] machine_hall.zip from ETH Research Collection (~12.6 GB) ..."
  echo "           URL: ${EUROC_RC_MACHINE_HALL}"
  wget -c --progress=dot:giga -O "${MACHINE_HALL_ZIP}" "${EUROC_RC_MACHINE_HALL}"
}

extract_bag_from_archive() {
  local seq="$1"
  local bag="${DATA_ROOT}/euroc/${seq}.bag"
  local inner
  inner="$(archive_inner_path "${seq}")"

  if [[ -f "${bag}" ]]; then
    echo "[skip] ${seq}.bag"
    return 0
  fi

  [[ -f "${MACHINE_HALL_ZIP}" ]] || { echo "[error] missing ${MACHINE_HALL_ZIP}" >&2; return 1; }

  echo "[extract] ${inner} from archive ..."
  unzip -j -o "${MACHINE_HALL_ZIP}" "${inner}" -d "${DATA_ROOT}/euroc/"
}

download_gdrive_ros2() {
  local seq="$1"
  local dst="${DATA_ROOT}/euroc/${seq}_ros2"
  local archive="${DATA_ROOT}/euroc/${seq}_ros2.zip"
  local file_id
  file_id="$(gdrive_id "${seq}")"

  if [[ -d "${dst}" && -f "${dst}/metadata.yaml" ]]; then
    echo "[skip] ${seq}_ros2"
    return 0
  fi

  source_venv
  pip install -q 'gdown>=5.0.0'
  echo "[download] ${seq} from Google Drive (may fail — use --source ethz-rc) ..."
  gdown "https://drive.google.com/uc?id=${file_id}" -O "${archive}"

  rm -rf "${dst}"
  unzip -q -o "${archive}" -d "${DATA_ROOT}/euroc/"
  if [[ ! -f "${dst}/metadata.yaml" ]]; then
    local found
    found="$(find "${DATA_ROOT}/euroc" -maxdepth 3 -name metadata.yaml | head -1 || true)"
    [[ -n "${found}" ]] && mv "$(dirname "${found}")" "${dst}"
  fi
  [[ -f "${dst}/metadata.yaml" ]] || { echo "[error] ROS2 bag not found for ${seq}" >&2; return 1; }
  rm -f "${archive}"
}

download_ethz_legacy_bag() {
  local seq="$1"
  local bag="${DATA_ROOT}/euroc/${seq}.bag"
  local url="http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/machine_hall/${seq}/${seq}.bag"

  if [[ -f "${bag}" ]]; then
    echo "[skip] ${seq}.bag"
    return 0
  fi

  echo "[download] ${seq}.bag from robotics.ethz.ch (often unreachable) ..."
  wget -c --timeout=30 --tries=3 -O "${bag}" "${url}"
}

download_custom_url() {
  local seq="$1"
  local url bag
  url="$(python3 "${SCRIPT_DIR}/lib/datasets_registry.py" meta "${seq}" bag 2>/dev/null || true)"
  bag="${DATA_ROOT}/euroc/${seq}.bag"
  if [[ -f "${bag}" ]]; then
    echo "[skip] ${seq}.bag (custom)"
    return 0
  fi
  # Expect JSON-like from meta bag field — use python helper
  local dl_url
  dl_url="$(python3 - <<PY
import json, sys
sys.path.insert(0, "${SCRIPT_DIR}/lib")
from datasets_registry import get_sequence
b = get_sequence("${seq}").get("bag") or {}
print(b.get("url", ""))
PY
)"
  [[ -n "${dl_url}" ]] || { echo "[error] no bag.url for custom ${seq}" >&2; return 1; }
  echo "[download] custom ${seq} from URL ..."
  wget -c --progress=dot:giga -O "${bag}" "${dl_url}"
}

convert_to_ros2() {
  local seq="$1"
  local bag="${DATA_ROOT}/euroc/${seq}.bag"
  local dst="${DATA_ROOT}/euroc/${seq}_ros2"

  if [[ -d "${dst}" && -f "${dst}/metadata.yaml" ]]; then
    echo "[skip] ${seq}_ros2 (converted)"
    return 0
  fi
  [[ -f "${bag}" ]] || { echo "[error] missing ${bag}" >&2; return 1; }

  source_venv
  pip install -q 'rosbags>=0.9.11'
  echo "[convert] ${seq}.bag -> ${dst}"
  rosbags-convert --src "${bag}" --dst "${dst}" --dst-typestore ros2_jazzy
}

is_custom_seq() {
  local seq="$1"
  python3 - <<PY
import sys
sys.path.insert(0, "${SCRIPT_DIR}/lib")
from datasets_registry import get_sequence
print(get_sequence("${seq}").get("family") == "custom")
PY
}

echo "Source: ${EUROC_SOURCE}  Sequences: ${SEQS[*]}  ROS2 convert: ${DO_ROS2}"
echo "Data root: ${DATA_ROOT}/euroc"
echo ""

for seq in "${SEQS[@]}"; do
  if [[ "$(is_custom_seq "${seq}")" == "True" ]]; then
    download_custom_url "${seq}" || true
    if ${DO_ROS2}; then
      convert_to_ros2 "${seq}"
    fi
    continue
  fi

  case "${EUROC_SOURCE}" in
    ethz-rc)
      download_machine_hall_archive
      extract_bag_from_archive "${seq}"
      if ${DO_ROS2}; then
        convert_to_ros2 "${seq}"
      fi
      ;;
    gdrive)
      download_gdrive_ros2 "${seq}"
      ;;
    ethz-legacy)
      download_ethz_legacy_bag "${seq}"
      if ${DO_ROS2}; then
        convert_to_ros2 "${seq}"
      fi
      ;;
    *)
      echo "Unknown source=${EUROC_SOURCE}" >&2
      exit 1
      ;;
  esac
done

echo ""
echo "Done. Datasets in ${DATA_ROOT}/euroc"
python3 "${SCRIPT_DIR}/lib/datasets_registry.py" list 2>/dev/null || ls -lh "${DATA_ROOT}/euroc/" 2>/dev/null || true
df -h "${DATA_ROOT}"
