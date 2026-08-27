#!/usr/bin/env bash
# Длинный безпризорный прогон статьи: compare, затем ablation.
# Не останавливается, если часть ячеек compare сорвалась (нужен --resume, не abort).
#
# Рекомендуемый запуск:
#   tmux new -s paper
#   bash scripts/run_paper_unattended.sh
#   # отсоединиться: Ctrl-b, затем d
#   # вернуться: tmux attach -t paper
#
# Не усыпляйте хост/ВМ. Диск: ориентир ≥20 ГБ свободно.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -f "${ROOT}/venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "${ROOT}/venv/bin/activate"
fi

mkdir -p "${ROOT}/datasets/results/batches"
LOG="${ROOT}/datasets/results/batches/unattended_$(date +%Y%m%d_%H%M%S).log"

{
  echo "===== unattended paper batch ====="
  echo "start=$(date -Iseconds)"
  echo "cwd=${ROOT}"
  echo "HEAD=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "disk=$(df -h . | tail -1)"
  echo "log=${LOG}"
  echo

  echo "===== COMPARE $(date -Iseconds) ====="
  python3 scripts/run_batch.py --plan config/batch_paper.yaml
  echo "compare_exit=$? $(date -Iseconds)"
  echo

  echo "===== ABLATION $(date -Iseconds) ====="
  python3 scripts/run_batch.py --plan config/batch_ablation.yaml
  echo "ablation_exit=$? $(date -Iseconds)"
  echo "===== done $(date -Iseconds) ====="
} 2>&1 | tee "${LOG}"

echo
echo "Лог: ${LOG}"
echo "Resume compare:   python3 scripts/run_batch.py --resume datasets/results/batches/paper_main_<штамп>"
echo "Resume ablation:  python3 scripts/run_batch.py --resume datasets/results/batches/ablation_d1_<штамп>"
