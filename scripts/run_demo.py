#!/usr/bin/env python3
"""Interactive demo launcher for VIO + trust_estimator experiments."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import terminal_colors as tc  # noqa: E402

try:
    from datasets_registry import (  # noqa: E402
        download_via_script,
        is_installed,
        list_sequences,
        query,
        save_custom_sequence,
    )
except ImportError as exc:
    print(f"ERROR: datasets_registry: {exc}", file=sys.stderr)
    sys.exit(1)

RUN_EUROC = ROOT / "scripts" / "run_euroc.sh"
DOWNLOAD_SCRIPT = ROOT / "scripts" / "download_datasets.sh"

# Параметры расширенного меню (сохраняются между прогонами в сессии demo)
_SESSION_ADVANCED = None


@dataclass
class AdvancedParams:
    start_offset: int | None = None
    retries: int | None = None
    trust_tau: float | None = None

MODES = [
    ("adaptive", "Adaptive — с trust_estimator (адаптивная достоверность)"),
    ("baseline", "Baseline — классический OpenVINS без адаптации"),
    ("compare", "Сравнение — baseline, затем adaptive на одной последовательности"),
]

BAG_OPTIONS = [
    ("", "Чистый bag (оригинал EuRoC)"),
    ("gaussian:5", "D1 — Gaussian blur σ=5 (размытие)"),
    ("gaussian:9", "D1 — Gaussian blur σ=9 (сильное размытие)"),
    ("brightness:40", "D3 — засветка +40%"),
    ("brightness:60", "D3 — засветка +60%"),
]

DOWNLOAD_SOURCES = [
    ("ethz-rc", "ETH Research Collection (machine_hall.zip, рекомендуется)"),
    ("gdrive", "Google Drive (ROS2 zip на каждую последовательность)"),
    ("ethz-legacy", "robotics.ethz.ch (часто недоступен)"),
]

_SUBPROC_ENV = {**os.environ, "DEMO_COLOR": "1"}


def _sequence_menu_options(*, only_installed: bool = False) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for row in list_sequences():
        if only_installed and not row["installed"]:
            continue
        mark = f"{tc.green('✓')}" if row["installed"] else f"{tc.yellow('·')}"
        gt = f"{tc.dim('GT')}" if row["has_gt"] else ""
        desc = f"{mark} {row['label']} {gt}".strip()
        options.append((row["id"], desc))
    return options


def _all_sequence_ids() -> list[str]:
    return [r["id"] for r in list_sequences()]


def _banner(text: str) -> None:
    line = "═" * 62
    print(f"\n{tc.blue(line)}")
    print(f"  {tc.white(text)}")
    print(f"{tc.blue(line)}\n")


def _menu(title: str, options: list[tuple[str, str]], *, allow_back: bool = False) -> str | None:
    print(tc.white(title))
    print()
    for i, (_key, desc) in enumerate(options, 1):
        print(f"  {tc.cyan(f'[{i}]')} {desc}")
    if allow_back:
        print(f"  {tc.dim('[0] Назад')}")
    else:
        print(f"  {tc.dim('[0] Выход')}")
    print()
    while True:
        raw = input(f"{tc.cyan('Выбор:')} ").strip()
        if raw in ("0", "q", "quit", "exit"):
            if allow_back:
                return None
            raise SystemExit(0)
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        print(f"  {tc.yellow('Неверный выбор, попробуйте снова.')}")


def _menu_exit_on_zero(title: str, options: list[tuple[str, str]]) -> str:
    result = _menu(title, options, allow_back=False)
    assert result is not None
    return result


def _build_run_cmd(
    mode: str,
    seq: str,
    duration: int | None,
    viz: bool,
    eval_ate: bool,
    quiet: bool,
    degrade: str,
    advanced: AdvancedParams | None = None,
) -> list[str]:
    cmd = ["bash", str(RUN_EUROC), mode, seq]
    if duration is not None:
        cmd.extend(["--duration", str(duration)])
    if degrade:
        cmd.extend(["--degrade", degrade])
    if viz:
        cmd.append("--viz")
    if eval_ate:
        cmd.append("--eval")
    if quiet:
        cmd.append("--quiet")
    adv = advanced or _SESSION_ADVANCED
    if adv:
        if adv.start_offset is not None:
            cmd.extend(["--start-offset", str(adv.start_offset)])
        if adv.retries is not None:
            cmd.extend(["--retries", str(adv.retries)])
        if adv.trust_tau is not None and mode in ("adaptive", "compare"):
            cmd.extend(["--trust-tau", str(adv.trust_tau)])
    return cmd


def _run(cmd: list[str], *, capture: bool = False) -> tuple[int, str | None]:
    print(f"\n{tc.dim('→')} {tc.dim(' '.join(cmd))}\n")
    if capture:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=_SUBPROC_ENV)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, file=sys.stderr, end="")
        if tc.colors_enabled():
            print(tc.reset(), end="")
        out_dir = None
        for line in proc.stdout.splitlines():
            m = re.match(r"RESULT_DIR=(.+)", line.strip())
            if m:
                out_dir = m.group(1)
        return proc.returncode, out_dir
    rc = subprocess.call(cmd, env=_SUBPROC_ENV)
    if tc.colors_enabled():
        print(tc.reset(), end="")
    return rc, None


def _print_compare_table(
    seq: str, baseline_dir: str, adaptive_dir: str, *, degraded: bool
) -> None:
    degraded_flag = "true" if degraded else "false"
    script = (
        f"source '{ROOT}/scripts/lib.sh' && "
        f"source '{ROOT}/scripts/lib/euroc_common.sh' && "
        f"euroc_print_compare_table '{seq}' '{baseline_dir}' '{adaptive_dir}' '{degraded_flag}'"
    )
    subprocess.run(["bash", "-c", script], check=False, env=_SUBPROC_ENV)


def _warn_seq_limits(seq: str, eval_ate: bool, mode: str) -> None:
    rows = {r["id"]: r for r in list_sequences()}
    row = rows.get(seq)
    if row and not row["has_gt"] and eval_ate:
        print(
            f"\n  {tc.yellow('Примечание:')} для {seq} нет ground truth в проекте — ATE будет пропущен.\n"
            "  Для сравнения с метриками выберите MH_04_difficult или MH_05_difficult.\n"
        )


def _advanced_params_menu(seq: str | None = None) -> AdvancedParams:
    global _SESSION_ADVANCED
    default_off = 0
    if seq:
        off = query(seq, "start_offset")
        default_off = int(off) if off else 0
    cur = _SESSION_ADVANCED or AdvancedParams()
    print(f"\n{tc.white('── Расширенные параметры ──')}")
    print(tc.dim("Enter — оставить значение по умолчанию из config/datasets.yaml\n"))

    raw = input(f"  start-offset, с [{cur.start_offset if cur.start_offset is not None else default_off}]: ").strip()
    start_offset = int(raw) if raw.isdigit() else cur.start_offset

    raw = input(f"  retries при расхождении [{cur.retries if cur.retries is not None else 3}]: ").strip()
    retries = int(raw) if raw.isdigit() else cur.retries

    raw = input(f"  trust_tau (adaptive) [{cur.trust_tau if cur.trust_tau is not None else 5.0}]: ").strip()
    trust_tau: float | None
    if raw:
        try:
            trust_tau = float(raw)
        except ValueError:
            trust_tau = cur.trust_tau
    else:
        trust_tau = cur.trust_tau

    _SESSION_ADVANCED = AdvancedParams(
        start_offset=start_offset,
        retries=retries,
        trust_tau=trust_tau,
    )
    print(f"  {tc.green('✓')} Сохранено для этой сессии demo")
    return _SESSION_ADVANCED


def _prompt_download(seq_id: str) -> bool:
    if is_installed(seq_id):
        return True
    print(f"\n  {tc.yellow('!')} Bag для {seq_id} не найден локально.")
    if input(f"  Скачать сейчас? [Y/n]: ").strip().lower() in ("", "y", "yes", "да", "д"):
        source = _menu_exit_on_zero("Источник загрузки:", DOWNLOAD_SOURCES)
        rc = download_via_script([seq_id], source=source, ros2=True)
        if rc != 0:
            print(f"  {tc.red('✗')} Загрузка не удалась (код {rc})")
            return False
        print(f"  {tc.green('✓')} {seq_id} готов к прогону")
        return is_installed(seq_id)
    return False


def _datasets_menu() -> None:
    while True:
        print()
        print(tc.white("── Датасеты ──"))
        print(f"  {tc.cyan('[1]')} Список (установленные / все)")
        print(f"  {tc.cyan('[2]')} Скачать последовательность")
        print(f"  {tc.cyan('[3]')} Скачать набор minimal / full")
        print(f"  {tc.cyan('[4]')} Добавить пользовательский bag")
        print(f"  {tc.dim('[0]')} Назад")
        choice = input(f"{tc.cyan('Выбор:')} ").strip()
        if choice in ("0", "q", "back", ""):
            return
        if choice == "1":
            print()
            subprocess.call(
                [sys.executable, str(ROOT / "scripts/lib/datasets_registry.py"), "list"],
                env=_SUBPROC_ENV,
            )
        elif choice == "2":
            seq = _menu_exit_on_zero("Последовательность для загрузки:", _sequence_menu_options())
            source = _menu_exit_on_zero("Источник:", DOWNLOAD_SOURCES)
            download_via_script([seq], source=source, ros2=True)
        elif choice == "3":
            bundle = _menu_exit_on_zero(
                "Набор:",
                [("minimal", "minimal — MH_01, MH_04, MH_05"), ("full", "full — все MH_01…05")],
            )
            source = _menu_exit_on_zero("Источник:", DOWNLOAD_SOURCES)
            subprocess.call(
                [
                    sys.executable,
                    str(ROOT / "scripts/lib/datasets_registry.py"),
                    "download",
                    "--bundle",
                    bundle,
                    "--source",
                    source,
                ],
                env=_SUBPROC_ENV,
            )
        elif choice == "4":
            _register_custom_dataset()
        else:
            print(f"  {tc.yellow('Неверный выбор.')}")


def _register_custom_dataset() -> None:
    print(f"\n{tc.white('Регистрация пользовательского bag')}")
    print(tc.dim("Запись сохраняется в config/datasets_custom.yaml\n"))
    seq_id = input("  ID (латиница, напр. my_flight_01): ").strip()
    if not seq_id or not re.match(r"^[A-Za-z0-9_+-]+$", seq_id):
        print(f"  {tc.red('✗')} Некорректный ID")
        return
    label = input("  Описание: ").strip() or seq_id
    print("  Тип bag:")
    print("    [1] Локальная папка ROS2 bag (metadata.yaml)")
    print("    [2] URL на ROS1 .bag (скачается и конвертируется)")
    kind = input("  Выбор [1]: ").strip() or "1"
    entry: dict = {
        "family": "custom",
        "label": label,
        "openvins_config": "euroc_mav",
        "start_offset": 0,
        "expected_path_m": None,
        "gt_file": None,
    }
    if kind == "2":
        url = input("  URL для wget: ").strip()
        if not url.startswith(("http://", "https://")):
            print(f"  {tc.red('✗')} Нужен http(s) URL")
            return
        entry["bag"] = {"type": "url", "url": url}
    else:
        path = input("  Путь к папке bag (от корня проекта или абсолютный): ").strip()
        entry["bag"] = {"type": "local", "path": path}
    off = input("  Start-offset, с [0]: ").strip()
    if off.isdigit():
        entry["start_offset"] = int(off)
    gt = input("  Файл GT (TUM, опционально): ").strip()
    if gt:
        entry["gt_file"] = gt
    save_custom_sequence(seq_id, entry)
    print(f"  {tc.green('✓')} Добавлено: {seq_id} → config/datasets_custom.yaml")


def _run_compare(
    seq: str,
    duration: int | None,
    eval_ate: bool,
    degrade: str,
    advanced: AdvancedParams | None = None,
) -> int:
    print(
        f"\n  {tc.dim('Режим «Сравнение» всегда headless (без RViz) для обоих прогонов.')}\n"
        f"  {tc.dim('RViz только в одиночном режиме adaptive/baseline (--viz).')}\n"
    )
    _warn_seq_limits(seq, eval_ate, "compare")
    subprocess.run(
        [
            "bash",
            "-c",
            f"source '{ROOT}/scripts/lib.sh' && "
            f"source '{ROOT}/scripts/lib/euroc_common.sh' && "
            "euroc_kill_stale_ros && sleep 2",
        ],
        check=False,
        env=_SUBPROC_ENV,
    )
    dirs: dict[str, str] = {}
    for m, label in [("baseline", "Baseline"), ("adaptive", "Adaptive")]:
        print(f"{tc.blue('─' * 44)}")
        print(f"  {tc.white('Запуск:')} {label}")
        print(f"{tc.blue('─' * 44)}")
        rc, out_dir = _run(
            _build_run_cmd(m, seq, duration, False, eval_ate, False, degrade, advanced),
            capture=True,
        )
        if rc != 0:
            return rc
        if out_dir:
            dirs[m] = out_dir
        if m == "baseline":
            subprocess.run(
                [
                    "bash",
                    "-c",
                    f"source '{ROOT}/scripts/lib.sh' && "
                    f"source '{ROOT}/scripts/lib/euroc_common.sh' && "
                    "euroc_kill_stale_ros",
                ],
                check=False,
                env=_SUBPROC_ENV,
            )
    if len(dirs) == 2 and eval_ate:
        _print_compare_table(seq, dirs["baseline"], dirs["adaptive"], degraded=bool(degrade))
    print(f"\n{tc.green('✓')} Сравнение завершено.")
    return 0


def _experiment_flow() -> None:
    mode = _menu_exit_on_zero("1. Режим работы:", MODES)
    seq_options = _sequence_menu_options()
    seq = _menu_exit_on_zero("2. Последовательность (✓ = установлена):", seq_options)
    if not is_installed(seq) and not _prompt_download(seq):
        print(f"  {tc.red('✗')} Нет bag для {seq}, прогон отменён.")
        return

    degrade = _menu_exit_on_zero("3. Качество изображений (bag):", BAG_OPTIONS)

    print(tc.white("4. Длительность воспроизведения bag:"))
    print(f"   {tc.cyan('[1]')} 60 с — быстрый demo")
    print(f"   {tc.cyan('[2]')} 120 с — средний")
    print(f"   {tc.cyan('[3]')} Полный bag (~2–3 мин, с учётом start-offset)")
    print(f"   {tc.dim('[0] Назад / выход')}")
    dur_choice = input(f"{tc.cyan('Выбор:')} ").strip()
    duration_map = {"1": 60, "2": 120, "3": None}
    duration = duration_map.get(dur_choice)
    if dur_choice == "0":
        return

    if mode == "compare":
        viz = False
        eval_ate = input("5. Посчитать ATE после прогона? [y/N]: ").strip().lower() in (
            "y",
            "yes",
            "да",
            "д",
        )
        step_adv = "6"
    else:
        viz = input("5. Открыть RViz? [y/N]: ").strip().lower() in ("y", "yes", "да", "д")
        eval_ate = input("6. Посчитать ATE после прогона? [y/N]: ").strip().lower() in (
            "y",
            "yes",
            "да",
            "д",
        )
        step_adv = "7"

    if input(f"{step_adv}. Расширенные параметры (offset, retries, trust_tau)? [y/N]: ").strip().lower() in (
        "y",
        "yes",
        "да",
        "д",
    ):
        _advanced_params_menu(seq)

    _warn_seq_limits(seq, eval_ate, mode)
    if degrade:
        print(
            f"\n  {tc.magenta('Деградация:')} {degrade} — при первом запуске bag будет "
            "собран автоматически (~1–2 мин).\n"
        )

    print()
    if mode == "compare":
        raise SystemExit(_run_compare(seq, duration, eval_ate, degrade, _SESSION_ADVANCED))
    rc, _ = _run(
        _build_run_cmd(mode, seq, duration, viz, eval_ate, False, degrade, _SESSION_ADVANCED),
        capture=False,
    )
    raise SystemExit(rc)


def interactive() -> None:
    _banner("VIO + Trust Estimator — демо-запуск")

    print(
        "Система оценивает достоверность визуальных измерений и "
        "адаптирует шум (ковариацию) в фильтре OpenVINS.\n"
        "Прогон идёт по записанному EuRoC-набору (камера + IMU).\n"
        f"{tc.magenta('Гипотеза')} проверяется на деградированных изображениях; "
        "на чистых данных adaptive должен быть ≈ baseline.\n"
    )

    while True:
        print(tc.white("Главное меню:"))
        print(f"  {tc.cyan('[1]')} Запуск эксперимента")
        print(f"  {tc.cyan('[2]')} Датасеты (скачать / добавить / список)")
        print(f"  {tc.cyan('[3]')} Расширенные параметры (offset, retries, trust_tau)")
        print(f"  {tc.dim('[0]')} Выход")
        choice = input(f"{tc.cyan('Выбор:')} ").strip()
        if choice in ("0", "q", "quit", "exit"):
            raise SystemExit(0)
        if choice == "1":
            _experiment_flow()
        elif choice == "2":
            _datasets_menu()
        elif choice == "3":
            _advanced_params_menu()
        else:
            print(f"  {tc.yellow('Неверный выбор.')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demo launcher for EuRoC baseline/adaptive runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--mode", choices=["baseline", "adaptive", "compare"], help="Run mode")
    parser.add_argument("--seq", default="MH_01_easy", help="Sequence id from config/datasets.yaml")
    parser.add_argument("--duration", type=int, default=None, help="Playback seconds")
    parser.add_argument(
        "--degrade",
        default="",
        help="Degrade spec TYPE:LEVEL (e.g. gaussian:5, brightness:40)",
    )
    parser.add_argument("--viz", action="store_true", help="Open RViz")
    parser.add_argument("--eval", action="store_true", dest="eval_ate", help="Compute ATE/RPE")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--start-offset", type=int, default=None, help="Override start-offset (s)")
    parser.add_argument("--retries", type=int, default=None, help="Max retries on divergence")
    parser.add_argument("--trust-tau", type=float, default=None, help="trust_tau for adaptive")
    parser.add_argument("--quick", action="store_true", help="Quick adaptive demo: MH_01_easy, 60 s")
    parser.add_argument(
        "--datasets",
        action="store_true",
        help="Open dataset management menu (download / custom)",
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

    cli_advanced = AdvancedParams(
        start_offset=args.start_offset,
        retries=args.retries,
        trust_tau=args.trust_tau,
    )
    if any(v is not None for v in (args.start_offset, args.retries, args.trust_tau)):
        global _SESSION_ADVANCED
        _SESSION_ADVANCED = cli_advanced

    if args.datasets:
        _datasets_menu()
        return 0

    if args.mode is None:
        interactive()
        return 0

    if args.seq not in _all_sequence_ids():
        print(f"ERROR: unknown sequence {args.seq!r}", file=sys.stderr)
        return 1
    if not is_installed(args.seq):
        print(f"ERROR: bag not installed for {args.seq}. Run:", file=sys.stderr)
        print(f"  bash {DOWNLOAD_SCRIPT} --seq {args.seq} --ros2", file=sys.stderr)
        return 1

    if args.mode == "compare":
        return _run_compare(args.seq, args.duration, args.eval_ate, args.degrade, _SESSION_ADVANCED)

    rc, _ = _run(
        _build_run_cmd(
            args.mode,
            args.seq,
            args.duration,
            args.viz,
            args.eval_ate,
            args.quiet,
            args.degrade,
            _SESSION_ADVANCED,
        ),
        capture=False,
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
