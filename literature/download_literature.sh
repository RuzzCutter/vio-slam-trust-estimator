#!/usr/bin/env bash
# Скачивание открытых PDF из Списка_литературы.txt
# Запуск: bash literature/download_literature.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDF="$ROOT/literature/pdf"
mkdir -p "$PDF"

download() {
  local num="$1" name="$2" url="$3"
  local out="$PDF/${num}_${name}.pdf"
  echo "[$num] $name"
  if curl -fsSL --max-time 180 -A "Mozilla/5.0" -o "$out" "$url"; then
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
download 03 OKVIS                  https://www.doc.ic.ac.uk/~sleutene/publications/ijrr2014_revision_1.pdf
download 04 Preintegration           https://arxiv.org/pdf/1512.02363.pdf
download 05 ORB-SLAM2              https://arxiv.org/pdf/1610.06475.pdf
download 06 Huang2010_Observability https://people.csail.mit.edu/ghuang/paper/Huang2009IJRR.pdf || \
download 06 Huang2010_Observability https://udel.edu/~ghuang/papers/tr_huang2010ijrr.pdf
download 07 Li2013_MSCKF           https://pdfs.semanticscholar.org/0be0/c13803cd08e81b7adaada537e91222eb1491.pdf
download 08 OpenVINS               https://pgeneva.com/downloads/papers/Geneva2020ICRA.pdf
download 09 Sun2017_substitute_VO_PartII http://rpg.ifi.uzh.ch/docs/VO_Part_II_Scaramuzza.pdf
download 10 SuperPoint             https://arxiv.org/pdf/1712.07629.pdf
download 11 SuperGlue              https://arxiv.org/pdf/1911.11763.pdf
download 12 Brachmann_LessMore     https://arxiv.org/pdf/1711.10228.pdf
download 12b Brachmann_DSAC2017    https://www.nowozin.net/sebastian/papers/brachmann2017dsac.pdf
download 13 DROID-SLAM             https://arxiv.org/pdf/2108.00669.pdf
download 14 Eigen_Depth            https://arxiv.org/pdf/1406.2283.pdf
download 15 DPT                    https://arxiv.org/pdf/2103.13413.pdf
download 16 AdaBins                https://arxiv.org/pdf/2011.14157.pdf
download 20 Zaffar_VPR-Bench       https://link.springer.com/content/pdf/10.1007/s11263-021-01469-5.pdf
download 21 KITTI                  https://www.cvlibs.net/publications/Geiger2012CVPR.pdf
download 23 TUM-VI                 https://arxiv.org/pdf/1804.06120.pdf

# MDPI / IEEE / SAGE — часто требуют браузер или подписку
download 17 Song2024_Sensors       "https://www.mdpi.com/1424-8220/24/20/6665/pdf?version=1728441600" || true
download 19 Kim2021_AdverseWeather "https://par.nsf.gov/servlets/purl/10345678" || true
download 22 EuRoC                  "https://www.research-collection.ethz.ch/bitstream/20.500.11850/120383/2/ijrr2016.pdf" || true

echo "Done. See literature/INDEX.md"
