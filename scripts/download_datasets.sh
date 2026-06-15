#!/usr/bin/env bash
# Download EuRoC and TUM-VI subsets for the experiment.
# Usage: bash download_datasets.sh [minimal|full]
set -euo pipefail

MODE="${1:-minimal}"
DATA_ROOT="${DATA_ROOT:-/home/g-tancyura/aspiranture/datasets}"
mkdir -p "${DATA_ROOT}"

download_euroc() {
  local seq="$1"
  local url="http://robotics.ethz.ch/~asl-datasets/ijrr_euroc_mav_dataset/machine_hall/${seq}/${seq}.zip"
  local dest="${DATA_ROOT}/euroc/${seq}"
  if [[ -d "${dest}/mav0" ]]; then
    echo "[skip] EuRoC ${seq} already present"
    return
  fi
  mkdir -p "${DATA_ROOT}/euroc"
  echo "[download] EuRoC ${seq} ..."
  wget -c -O "${DATA_ROOT}/euroc/${seq}.zip" "${url}"
  unzip -q "${DATA_ROOT}/euroc/${seq}.zip" -d "${DATA_ROOT}/euroc"
}

download_tum() {
  local name="$1"
  local url="https://vision.in.tum.de/tumvi/exported/euroc-style/${name}.zip"
  local dest="${DATA_ROOT}/tum_vi/${name}"
  if [[ -d "${dest}/mav0" ]]; then
    echo "[skip] TUM-VI ${name} already present"
    return
  fi
  mkdir -p "${DATA_ROOT}/tum_vi"
  echo "[download] TUM-VI ${name} ..."
  wget -c -O "${DATA_ROOT}/tum_vi/${name}.zip" "${url}"
  unzip -q "${DATA_ROOT}/tum_vi/${name}.zip" -d "${DATA_ROOT}/tum_vi"
}

case "${MODE}" in
  minimal)
    download_euroc "MH_01_easy"
    download_euroc "MH_04_difficult"
    download_euroc "MH_05_difficult"
    download_tum "dataset-corridor2_512_03"
    download_tum "dataset-room2_512_01"
    ;;
  full)
    for s in MH_01_easy MH_02_easy MH_03_medium MH_04_difficult MH_05_difficult; do
      download_euroc "${s}"
    done
    for s in dataset-corridor2_512_03 dataset-room2_512_01 dataset-magistrale2_512_04; do
      download_tum "${s}"
    done
    ;;
  *)
    echo "Usage: $0 [minimal|full]"
    exit 1
    ;;
esac

echo "Done. Datasets in ${DATA_ROOT}"
df -h "${DATA_ROOT}"
