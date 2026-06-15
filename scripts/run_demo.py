#!/usr/bin/env python3
"""
Interactive demo launcher for VIO + trust_estimator experiments.

For a quick non-interactive run:
  python3 scripts/run_demo.py --quick
  python3 scripts/run_demo.py --mode adaptive --seq MH_01_easy --duration 60
  python3 scripts/run_demo.py --compare --duration 90 --eval
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_EUROC = ROOT / "scripts" / "run_euroc.sh"

SEQUENCES = [
    ("MH_01_easy", "Machine Hall — лёгкий (smoke-test, ~80 м)"),
    ("MH_04_difficult", "Machine Hall — сложный (для сравнения baseline/adaptive)"),
    ("MH_05_difficult", "Machine Hall — сложный #2"),
]

MODES = [
    ("adaptive", "Adaptive — с trust_estimator (адаптивная достоверность)"),
    ("baseline", "Baseline — классический OpenVINS без адаптации"),
    ("compare", "Сравнение — baseline, затем adaptive на одной последовательности"),
]


def _banner(text: str) -> None:
    line = "═" * 62
    print(f"\n{line}\n  {text}\n{line}\n")


def _menu(title: str, options: list[tuple[str, str]]) -> str:
    print(title)
    print()
    for i, (key, desc) in enumerate(options, 1):
        print(f"  [{i}] {desc}")
    print(f"  [0] Выход")
    print()
    while True:
        raw = input("Выбор: ").strip()
        if raw in ("0", "q", "quit", "exit"):
            raise SystemExit(0)
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        print("  Неверный выбор, попробуйте снова.")


def _run(cmd: list[str], verbose: bool = True) -> int:
    if verbose:
        print(f"\n→ {' '.join(cmd)}\n")
    return subprocess.call(cmd)


def _build_run_cmd(
    mode: str,
    seq: str,
    duration: int | None,
    viz: bool,
    eval_ate: bool,
    quiet: bool,
) -> list[str]:
    cmd = ["bash", str(RUN_EUROC), mode, seq]
    if duration is not None:
        cmd.extend(["--duration", str(duration)])
    if viz:
        cmd.append("--viz")
    if eval_ate:
        cmd.append("--eval")
    if quiet:
        cmd.append("--quiet")
    return cmd


def interactive() -> None:
    _banner("VIO + Trust Estimator — демо-запуск")

    print(
        "Система оценивает достоверность визуальных измерений и "
        "адаптирует шум (ковариацию) в фильтре OpenVINS.\n"
        "Этот мастер запускает прогон на записанном EuRoC-наборе "
        "(камера + IMU, без реального робота).\n"
    )

    mode = _menu("1. Режим работы:", MODES)
    seq = _menu("2. Последовательность EuRoC:", SEQUENCES)

    print("3. Длительность воспроизведения bag:")
    print("   [1] 60 с — быстрый demo")
    print("   [2] 120 с — средний")
    print("   [3] Полный bag (~2–3 мин после offset)")
    print("   [0] Назад / выход")
    dur_choice = input("Выбор: ").strip()
    duration_map = {"1": 60, "2": 120, "3": None}
    duration = duration_map.get(dur_choice)
    if dur_choice == "0":
        raise SystemExit(0)

    viz = input("4. Открыть RViz? [y/N]: ").strip().lower() in ("y", "yes", "да", "d")
    eval_ate = input("5. Посчитать ATE после прогона (MH_04/05)? [y/N]: ").strip().lower() in (
        "y",
        "yes",
        "да",
        "d",
    )

    print()
    if mode == "compare":
        for m, label in [("baseline", "Baseline"), ("adaptive", "Adaptive")]:
            print(f"{'─' * 40}\n  Запуск: {label}\n{'─' * 40}")
            rc = _run(_build_run_cmd(m, seq, duration, viz and m == "adaptive", eval_ate, False))
            if rc != 0:
                sys.exit(rc)
        print("\n✓ Сравнение завершено. Смотрите datasets/results/")
    else:
        rc = _run(_build_run_cmd(mode, seq, duration, viz, eval_ate, False))
        sys.exit(rc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demo launcher for EuRoC baseline/adaptive runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--mode", choices=["baseline", "adaptive", "compare"], help="Run mode")
    parser.add_argument("--seq", default="MH_01_easy", choices=[s[0] for s in SEQUENCES])
    parser.add_argument("--duration", type=int, default=None, help="Playback seconds")
    parser.add_argument("--viz", action="store_true", help="Open RViz")
    parser.add_argument("--eval", action="store_true", dest="eval_ate", help="Compute ATE/RPE")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick adaptive demo: MH_01_easy, 60 s",
    )
    args = parser.parse_args()

    if not RUN_EUROC.is_file():
        print(f"ERROR: missing {RUN_EUROC}", file=sys.stderr)
        return 1
    if shutil.which("bash") is None:
        print("ERROR: bash not found", file=sys.stderr)
        return 1

    if args.quick:
        args.mode = "adaptive"
        args.seq = "MH_01_easy"
        args.duration = 60

    if args.mode is None:
        interactive()
        return 0

    if args.mode == "compare":
        for m in ("baseline", "adaptive"):
            rc = _run(
                _build_run_cmd(m, args.seq, args.duration, args.viz, args.eval_ate, args.quiet)
            )
            if rc != 0:
                return rc
        return 0

    return _run(
        _build_run_cmd(args.mode, args.seq, args.duration, args.viz, args.eval_ate, args.quiet)
    )


if __name__ == "__main__":
    raise SystemExit(main())
