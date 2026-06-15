#!/usr/bin/env bash
# Download EuRoC datasets for OpenVINS on ROS 2 Jazzy.
#
# Default source: ETH Research Collection (robotics.ethz.ch often unreachable;
# Google Drive mirrors from OpenVINS frequently return permission errors).
#
# Usage:
#   bash download_datasets.sh minimal              # extract bags + ROS2 conversion
#   bash download_datasets.sh minimal --ros1-only  # bags only, no conversion
#   bash download_datasets.sh full
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

MODE="minimal"
DO_ROS2=true
EUROC_SOURCE="${EUROC_SOURCE:-ethz-rc}"

for arg in "$@"; do
  case "${arg}" in
    minimal|full) MODE="${arg}" ;;
    --ros1-only) DO_ROS2=false ;;
    --ros2) DO_ROS2=true ;;
    --ethz-rc) EUROC_SOURCE="ethz-rc" ;;
    --gdrive) EUROC_SOURCE="gdrive" ;;
    --ethz-legacy) EUROC_SOURCE="ethz-legacy" ;;
    *) echo "Unknown arg: ${arg}"; echo "Usage: $0 [minimal|full] [--ros1-only|--ros2] [--ethz-rc|--gdrive]"; exit 1 ;;
  esac
done

DATA_ROOT="${DATA_ROOT:-$(aspiranture_root)/datasets}"
mkdir -p "${DATA_ROOT}/euroc"

case "${MODE}" in
  minimal) SEQS=(MH_01_easy MH_04_difficult MH_05_difficult) ;;
  full)    SEQS=(MH_01_easy MH_02_easy MH_03_medium MH_04_difficult MH_05_difficult) ;;
esac

# ETH Research Collection — DOI 10.3929/ethz-b-000690084
EUROC_RC_MACHINE_HALL="https://www.research-collection.ethz.ch/server/api/core/bitstreams/7b2419c1-62b5-4714-b7f8-485e5fe3e5fe/content"
MACHINE_HALL_ZIP="${DATA_ROOT}/euroc/machine_hall.zip"

gdrive_id() {
  case "$1" in
    MH_01_easy)      echo "1UP4nkuSEOQECZTswwh9BPgfMl-dnDstA" ;;
    MH_02_easy)      echo "1wWZgZCqYz6zzzTXS0iqvQCP-cWfFuGLK" ;;
    MH_03_medium)    echo "1er07gZ8rso8R3Su00hJMm_GZ4z1n9Rpq" ;;
    MH_04_difficult) echo "1eC8joRXo1rh0wzOpq3e-B4dQ8-w6wZYz" ;;
    MH_05_difficult) echo "1zoN94K1Afrp7HXSduRLkJBiEjPKdk1UA" ;;
    *) echo "Unknown sequence: $1" >&2; return 1 ;;
  esac
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
  local inner="machine_hall/${seq}/${seq}.bag"

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
  echo "[download] ${seq} from Google Drive (may fail — use --ethz-rc) ..."
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

echo "Source: ${EUROC_SOURCE}  Mode: ${MODE}  ROS2 convert: ${DO_ROS2}"
echo "Data root: ${DATA_ROOT}/euroc"
echo ""

case "${EUROC_SOURCE}" in
  ethz-rc)
    download_machine_hall_archive
    for seq in "${SEQS[@]}"; do
      extract_bag_from_archive "${seq}"
      if ${DO_ROS2}; then
        convert_to_ros2 "${seq}"
      fi
    done
    ;;
  gdrive)
    for seq in "${SEQS[@]}"; do
      download_gdrive_ros2 "${seq}"
    done
    ;;
  ethz-legacy)
    for seq in "${SEQS[@]}"; do
      download_ethz_legacy_bag "${seq}"
      if ${DO_ROS2}; then
        convert_to_ros2 "${seq}"
      fi
    done
    ;;
  *)
    echo "Unknown EUROC_SOURCE=${EUROC_SOURCE}" >&2
    exit 1
    ;;
esac

echo ""
echo "Done. Datasets in ${DATA_ROOT}/euroc"
ls -lh "${DATA_ROOT}/euroc/" 2>/dev/null || true
for seq in "${SEQS[@]}"; do
  [[ -f "${DATA_ROOT}/euroc/${seq}.bag" ]] && echo "  ${seq}.bag: $(du -sh "${DATA_ROOT}/euroc/${seq}.bag" | awk '{print $1}')"
  [[ -d "${DATA_ROOT}/euroc/${seq}_ros2" ]] && echo "  ${seq}_ros2: $(du -sh "${DATA_ROOT}/euroc/${seq}_ros2" | awk '{print $1}')"
done
df -h "${DATA_ROOT}"
