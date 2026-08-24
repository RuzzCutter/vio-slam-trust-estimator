#!/usr/bin/env bash
# Скачивание открытых PDF. Номер файла = номер ссылки в Статья_v6.txt.
# Запуск: bash literature/download_literature.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDF="$ROOT/literature/pdf"
mkdir -p "$PDF"

download() {
  local num="$1" name="$2" url="$3"
  local out="$PDF/${num}_${name}.pdf"
  echo "[$num] $name"
  if curl -fsSL --max-time 180 -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" -o "$out" "$url"; then
    local size
    size=$(stat -c%s "$out" 2>/dev/null || echo 0)
    if [ "$size" -lt 5000 ]; then
      echo "  skip: file too small ($size bytes)"
      rm -f "$out"
      return 1
    fi
    echo "  ok ($size bytes)"
    return 0
  fi
  echo "  failed"
  rm -f "$out"
  return 1
}

download 01 ORB-SLAM3              https://arxiv.org/pdf/2007.11898.pdf
download 02 VINS-Mono              https://arxiv.org/pdf/1708.03852.pdf
download 03 ORB-SLAM2              https://arxiv.org/pdf/1610.06475.pdf
download 04 OKVIS                  https://www.doc.ic.ac.uk/~sleutene/publications/ijrr2014_revision_1.pdf
download 05 Preintegration           https://arxiv.org/pdf/1512.02363.pdf
download 06 OpenVINS               https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf
download 08 Zaffar_VPR-Bench       https://link.springer.com/content/pdf/10.1007/s11263-021-01469-5.pdf
download 11 KITTI                  https://www.cvlibs.net/publications/Geiger2012CVPR.pdf
download 12 TUM-VI                 https://arxiv.org/pdf/1804.06120.pdf
download 13 Bobkov2018             "https://ics.togudv.ru/media/2018/N56_02.pdf" || \
download 13 Bobkov2018             "https://ics.khstu.ru/media/2018/N56_02.pdf" || true
download 15 Li2013_MSCKF           https://pdfs.semanticscholar.org/0be0/c13803cd08e81b7adaada537e91222eb1491.pdf || true
download 17 YangGan_Gyroscopy2023  "https://cyberleninka.ru/article/n/ispolzovanie-klyuchevyh-tochek-i-liniy-izobrazheniya-v-zadache-vizualno-inertsialnoy-odometrii-v-realnom-vremeni/pdf" || true
download 18 SuperPoint             https://arxiv.org/pdf/1712.07629.pdf
download 19 SuperGlue              https://arxiv.org/pdf/1911.11763.pdf
download 20 Eigen_Depth            https://arxiv.org/pdf/1406.2283.pdf
download 21 DPT                    https://arxiv.org/pdf/2103.13413.pdf
download 22 AdaBins                https://arxiv.org/pdf/2011.14141.pdf
download 23 DROID-SLAM             https://arxiv.org/pdf/2108.10869.pdf || \
download 23 DROID-SLAM             "https://proceedings.neurips.cc/paper/2021/file/89fcd07f20b6785b92134bd6c1d0fa42-Paper.pdf"
download 26 Huang2010_Observability https://people.csail.mit.edu/ghuang/paper/Huang2010IJRR.pdf || \
download 26 Huang2010_Observability https://people.csail.mit.edu/ghuang/paper/Huang2009IJRR.pdf
download 27 Soifer2025             "https://ia.spcras.ru/index.php/sp/article/download/17415/15538" || true

# Paywall / 403 — пробуем, отсутствие файла допустимо
download 07 Kim2015_IROS           "https://www.pyojinkim.com/papers/IROS2015_pyojin.pdf" || true
download 09 EuRoC                  "https://www.research-collection.ethz.ch/bitstream/20.500.11850/120383/2/ijrr2016.pdf" || true
download 10 RANSAC_Fischler1981    "https://dl.acm.org/doi/pdf/10.1145/358669.358692" || true
download 24 Song2024_Sensors       "https://www.mdpi.com/1424-8220/24/20/6665/pdf" || true

echo "Done. See literature/INDEX.md"
