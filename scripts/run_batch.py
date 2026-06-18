#!/usr/bin/env python3
"""Unattended batch runs for paper experiments (compare or ablation).

Reads a YAML plan, writes manifest.jsonl under datasets/results/batches/<batch_id>/.

Examples:
  python3 scripts/run_batch.py --plan config/batch_paper.yaml
  python3 scripts/run_batch.py --plan config/batch_ablation.yaml
  python3 scripts/run_batch.py --resume datasets/results/batches/ablation_d1_...
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from run_results import (  # noqa: E402
    ablate_spec_to_variant,
    compare_from_dirs,
    degrade_spec_to_label,
    load_run_record,
)

RUN_DEMO = ROOT / "scripts" / "run_demo.py"
RUN_EUROC = ROOT / "scripts" / "run_euroc.sh"
DEFAULT_RESULTS = ROOT / "datasets" / "results"


def load_plan(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise SystemExit("PyYAML required: pip install pyyaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "runs" not in data:
        raise SystemExit(f"Invalid plan (need 'runs' list): {path}")
    return data


def plan_kind(plan: dict[str, Any]) -> str:
    kind = (plan.get("kind") or plan.get("mode") or "compare").lower()
    if kind in ("ablation", "adaptive"):
        return "ablation"
    return "compare"


def _parse_result_dirs(stdout: str) -> list[str]:
    dirs: list[str] = []
    for line in stdout.splitlines():
        m = re.match(r"RESULT_DIR=(.+)", line.strip())
        if m:
            dirs.append(m.group(1))
    return dirs


def run_compare_cell(
    *,
    seq: str,
    degrade: str,
    duration: int | None,
    eval_ate: bool,
    advanced: dict[str, Any],
    quiet: bool,
) -> tuple[int, str | None, str | None, str]:
    cmd = [sys.executable, str(RUN_DEMO), "--mode", "compare", "--seq", seq]
    if duration is not None:
        cmd.extend(["--duration", str(duration)])
    if degrade:
        cmd.extend(["--degrade", degrade])
    if eval_ate:
        cmd.append("--eval")
    if quiet:
        cmd.append("--quiet")
    if advanced.get("start_offset") is not None:
        cmd.extend(["--start-offset", str(advanced["start_offset"])])
    if advanced.get("retries") is not None:
        cmd.extend(["--retries", str(advanced["retries"])])
    if advanced.get("trust_tau") is not None:
        cmd.extend(["--trust-tau", str(advanced["trust_tau"])])

    log_lines = [f"$ {' '.join(cmd)}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    combined = (proc.stdout or "") + (proc.stderr or "")
    log_lines.append(combined)
    dirs = _parse_result_dirs(proc.stdout or "")
    baseline_dir = dirs[0] if len(dirs) >= 1 else None
    adaptive_dir = dirs[1] if len(dirs) >= 2 else None
    return proc.returncode, baseline_dir, adaptive_dir, "\n".join(log_lines)


def run_adaptive_cell(
    *,
    seq: str,
    degrade: str,
    ablate: str,
    duration: int | None,
    eval_ate: bool,
    advanced: dict[str, Any],
    quiet: bool,
) -> tuple[int, str | None, str]:
    cmd = ["bash", str(RUN_EUROC), "adaptive", seq]
    if duration is not None:
        cmd.extend(["--duration", str(duration)])
    if degrade:
        cmd.extend(["--degrade", degrade])
    for feat in ablate.replace(",", " ").split():
        feat = feat.strip().lower()
        if feat:
            cmd.extend(["--ablate", feat])
    if eval_ate:
        cmd.append("--eval")
    if quiet:
        cmd.append("--quiet")
    if advanced.get("start_offset") is not None:
        cmd.extend(["--start-offset", str(advanced["start_offset"])])
    if advanced.get("retries") is not None:
        cmd.extend(["--retries", str(advanced["retries"])])
    if advanced.get("trust_tau") is not None:
        cmd.extend(["--trust-tau", str(advanced["trust_tau"])])

    log_lines = [f"$ {' '.join(cmd)}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    combined = (proc.stdout or "") + (proc.stderr or "")
    log_lines.append(combined)
    dirs = _parse_result_dirs(proc.stdout or "")
    return proc.returncode, (dirs[-1] if dirs else None), "\n".join(log_lines)


def _manifest_index(manifest_path: Path) -> set[int]:
    done: set[int] = set()
    if not manifest_path.is_file():
        return done
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") == "ok":
            done.add(int(row.get("index", -1)))
    return done


def _append_manifest(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _run_label(degrade: str, ablate: str) -> str:
    parts = [degrade_spec_to_label(degrade)]
    variant = ablate_spec_to_variant(ablate)
    if variant != "full":
        parts.append(f"ablate {variant}")
    return " | ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch runner for compare / ablation experiments")
    parser.add_argument("--plan", type=Path, default=ROOT / "config" / "batch_paper.yaml")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--id", dest="batch_id", default="", help="Batch id (default: from plan + timestamp)")
    parser.add_argument("--resume", type=Path, default=None, help="Existing batch directory to continue")
    parser.add_argument("--from", dest="from_index", type=int, default=1, help="Start from run index (1-based)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only")
    parser.add_argument("--no-quiet", action="store_true", help="Verbose run_euroc output")
    args = parser.parse_args()

    if args.resume:
        batch_dir = args.resume.resolve()
        plan_path = batch_dir / "batch_plan.yaml"
        if not plan_path.is_file():
            raise SystemExit(f"No batch_plan.yaml in {batch_dir}")
        plan = load_plan(plan_path)
        manifest_path = batch_dir / "manifest.jsonl"
        completed = _manifest_index(manifest_path)
    else:
        plan = load_plan(args.plan.resolve())
        completed = set()
        if args.dry_run:
            base_id = args.batch_id or plan.get("id", "batch")
            batch_dir = args.results_root / "batches" / f"{base_id}_<timestamp>"
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_id = args.batch_id or plan.get("id", "batch")
            batch_dir = (args.results_root / "batches" / f"{base_id}_{stamp}").resolve()
            batch_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.plan.resolve(), batch_dir / "batch_plan.yaml")
            manifest_path = batch_dir / "manifest.jsonl"

    runs: list[dict[str, Any]] = plan.get("runs") or []
    eval_ate = bool(plan.get("eval", True))
    duration = plan.get("duration")
    advanced = deepcopy(plan.get("advanced") or {})
    quiet = not args.no_quiet
    kind = plan_kind(plan)

    if args.dry_run:
        print(f"Batch directory (preview): {batch_dir}")
        print(f"Kind: {kind} | Runs: {len(runs)} | eval={eval_ate} | completed={len(completed)}")
        print()
        for i, run in enumerate(runs, start=1):
            seq = run["seq"]
            degrade = run.get("degrade") or ""
            ablate = run.get("ablate") or ""
            label = _run_label(degrade, ablate)
            skip = "SKIP" if i in completed else "RUN"
            print(f"  [{skip}] {i:02d}. {seq} | {label}")
        return 0

    manifest_path = batch_dir / "manifest.jsonl"

    print(f"Batch directory: {batch_dir}")
    print(f"Kind: {kind} | Runs: {len(runs)} | eval={eval_ate} | completed={len(completed)}")
    print()

    summary_path = batch_dir / "batch_summary.txt"
    t0 = time.time()
    failures = 0

    for i, run in enumerate(runs, start=1):
        if i < args.from_index:
            continue
        if i in completed:
            print(f"[{i:02d}/{len(runs)}] skip (already done)")
            continue

        seq = run["seq"]
        degrade = run.get("degrade") or ""
        ablate = run.get("ablate") or ""
        label = _run_label(degrade, ablate)
        print(f"[{i:02d}/{len(runs)}] {seq} | {label} ...", flush=True)

        if kind == "ablation":
            rc, adaptive_dir, log_text = run_adaptive_cell(
                seq=seq,
                degrade=degrade,
                ablate=ablate,
                duration=run.get("duration", duration),
                eval_ate=eval_ate,
                advanced=advanced,
                quiet=quiet,
            )
            baseline_dir = None
        else:
            rc, baseline_dir, adaptive_dir, log_text = run_compare_cell(
                seq=seq,
                degrade=degrade,
                duration=run.get("duration", duration),
                eval_ate=eval_ate,
                advanced=advanced,
                quiet=quiet,
            )

        ablate_tag = ablate.replace(":", "") or "full"
        log_file = batch_dir / f"run_{i:02d}_{seq}_{degrade.replace(':', '') or 'clean'}_{ablate_tag}.log"
        log_file.write_text(log_text, encoding="utf-8")

        ok = rc == 0 and (adaptive_dir if kind == "ablation" else (baseline_dir and adaptive_dir))
        row: dict[str, Any] = {
            "index": i,
            "kind": kind,
            "seq": seq,
            "degrade": degrade,
            "degrade_label": degrade_spec_to_label(degrade),
            "ablate": ablate,
            "ablate_variant": ablate_spec_to_variant(ablate),
            "status": "ok" if ok else "failed",
            "returncode": rc,
            "baseline_dir": baseline_dir,
            "adaptive_dir": adaptive_dir,
            "result_dir": adaptive_dir,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "log_file": str(log_file.relative_to(ROOT)),
        }

        if row["status"] == "ok":
            if kind == "ablation" and adaptive_dir:
                rec = load_run_record(adaptive_dir)
                row["ape_adaptive_m"] = rec.ape_rmse_m
                row["rpe_adaptive_m"] = rec.rpe_rmse_m
                row["c_mean"] = rec.c_mean
                print(f"    → APE {row['ape_adaptive_m']} m | c̄={row.get('c_mean')}")
            elif baseline_dir and adaptive_dir:
                cmp = compare_from_dirs(baseline_dir, adaptive_dir, batch_id=batch_dir.name, run_index=i)
                row["verdict"] = cmp.verdict()
                row["delta_ape_pct"] = cmp.delta_ape_pct()
                b, a = cmp.baseline, cmp.adaptive
                row["ape_baseline_m"] = b.ape_rmse_m if b else None
                row["ape_adaptive_m"] = a.ape_rmse_m if a else None
                print(
                    f"    → APE {row['ape_baseline_m']} / {row['ape_adaptive_m']} m | "
                    f"Δ={row['delta_ape_pct']:.1f}% | {row['verdict']}"
                    if row.get("delta_ape_pct") is not None
                    else "    → done (see log)"
                )
        else:
            failures += 1
            print(f"    ✗ failed (rc={rc}), log: {log_file.name}")

        _append_manifest(manifest_path, row)

    elapsed = time.time() - t0
    build_cmd = (
        f"python3 scripts/build_tables.py --batch {batch_dir} --kind ablation --out paper_tables/"
        if kind == "ablation"
        else f"python3 scripts/build_tables.py --batch {batch_dir} --out paper_tables/"
    )
    summary = (
        f"Batch {batch_dir.name}\n"
        f"Kind: {kind}\n"
        f"Finished at {datetime.now().isoformat(timespec='seconds')}\n"
        f"Runs: {len(runs)} | failures: {failures} | elapsed: {elapsed/60:.1f} min\n"
        f"Manifest: {manifest_path}\n"
        f"Build tables: {build_cmd}\n"
    )
    summary_path.write_text(summary, encoding="utf-8")
    print()
    print(summary)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
