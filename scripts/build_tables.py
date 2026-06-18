#!/usr/bin/env python3
"""Build paper tables (Markdown / LaTeX / CSV) from batch manifests or result dirs.

Examples:
  python3 scripts/build_tables.py --batch datasets/results/batches/paper_main_...
  python3 scripts/build_tables.py --batch datasets/results/batches/ablation_d1_... --kind ablation
  python3 scripts/build_tables.py --scan datasets/results --kind ablation --out paper_tables/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from run_results import (  # noqa: E402
    load_ablation_manifest,
    load_batch_manifest,
    render_ablation_csv,
    render_ablation_markdown,
    render_csv,
    render_latex_table,
    render_markdown_table,
    scan_ablation_results,
    scan_results_root,
    split_clean_degraded,
)


def _sort_key(row) -> tuple:
    order = {"clean": 0, "gaussian:5": 1, "gaussian:9": 2, "brightness:40": 3, "brightness:60": 4}
    return (row.seq, order.get(row.degrade, 99), row.degrade)


def _detect_kind(batch_dir: Path) -> str:
    plan = batch_dir / "batch_plan.yaml"
    if plan.is_file():
        text = plan.read_text(encoding="utf-8")
        if "kind: ablation" in text or "kind:ablation" in text.replace(" ", ""):
            return "ablation"
    manifest = batch_dir / "manifest.jsonl"
    if manifest.is_file():
        first = manifest.read_text(encoding="utf-8").splitlines()[0]
        if '"kind": "ablation"' in first or '"ablate"' in first:
            return "ablation"
    return "compare"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ATE/RPE tables for the paper")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--batch", type=Path, help="Batch directory with manifest.jsonl")
    src.add_argument("--scan", type=Path, help="Scan results root")
    parser.add_argument("--out", type=Path, default=ROOT / "paper_tables", help="Output directory")
    parser.add_argument(
        "--kind",
        choices=["compare", "ablation", "auto"],
        default="auto",
        help="Table type (auto: detect from batch plan)",
    )
    parser.add_argument(
        "--format",
        nargs="+",
        choices=["md", "latex", "csv"],
        default=["md", "latex", "csv"],
    )
    parser.add_argument("--title", default="EuRoC: baseline vs adaptive")
    args = parser.parse_args()

    kind = args.kind
    if args.batch and kind == "auto":
        kind = _detect_kind(args.batch.resolve())

    args.out.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    if kind == "ablation":
        if args.batch:
            groups = load_ablation_manifest(args.batch.resolve())
            source_label = args.batch.name
        else:
            groups = scan_ablation_results(args.scan.resolve())
            source_label = args.scan.name
        if not groups:
            print("No ablation groups found.", file=sys.stderr)
            return 1
        if "md" in args.format:
            p = args.out / "table_ablation.md"
            p.write_text(
                render_ablation_markdown(groups, title=f"Ablation f₁–f₄ ({source_label})"),
                encoding="utf-8",
            )
            outputs.append(p)
        if "csv" in args.format:
            p = args.out / "table_ablation.csv"
            p.write_text(render_ablation_csv(groups), encoding="utf-8")
            outputs.append(p)
        print(f"Ablation groups: {len(groups)}")
        for p in outputs:
            print(f"  {p}")
        return 0

    if args.batch:
        rows = load_batch_manifest(args.batch.resolve())
        source_label = args.batch.name
    else:
        rows = scan_results_root(args.scan.resolve())
        source_label = args.scan.name

    if not rows:
        print("No compare pairs found.", file=sys.stderr)
        return 1

    rows = sorted(rows, key=_sort_key)
    clean, degraded = split_clean_degraded(rows)

    if "md" in args.format:
        combined = render_markdown_table(rows, title=f"{args.title} ({source_label})")
        p = args.out / "table_all.md"
        p.write_text(combined, encoding="utf-8")
        outputs.append(p)
        if clean:
            p = args.out / "table_clean.md"
            p.write_text(render_markdown_table(clean, title="Чистые данные"), encoding="utf-8")
            outputs.append(p)
        if degraded:
            p = args.out / "table_degraded.md"
            p.write_text(render_markdown_table(degraded, title="Деградация D1/D3"), encoding="utf-8")
            outputs.append(p)

    if "latex" in args.format:
        p = args.out / "table_all.tex"
        p.write_text(
            render_latex_table(rows, caption=args.title, label="tab:ate_all"),
            encoding="utf-8",
        )
        outputs.append(p)

    if "csv" in args.format:
        p = args.out / "table_all.csv"
        p.write_text(render_csv(rows), encoding="utf-8")
        outputs.append(p)

    print(f"Rows: {len(rows)} (clean={len(clean)}, degraded={len(degraded)})")
    for p in outputs:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
