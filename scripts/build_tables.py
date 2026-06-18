#!/usr/bin/env python3
"""Build paper tables (Markdown / LaTeX / CSV) from batch manifests or result dirs.

Examples:
  python3 scripts/build_tables.py --batch datasets/results/batches/paper_main_20260618_120000
  python3 scripts/build_tables.py --scan datasets/results --out paper_tables/
  python3 scripts/build_tables.py --batch ... --format md latex csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from run_results import (  # noqa: E402
    load_batch_manifest,
    render_csv,
    render_latex_table,
    render_markdown_table,
    scan_results_root,
    split_clean_degraded,
)


def _sort_key(row) -> tuple:
    order = {"clean": 0, "gaussian:5": 1, "gaussian:9": 2, "brightness:40": 3, "brightness:60": 4}
    return (row.seq, order.get(row.degrade, 99), row.degrade)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ATE/RPE tables for the paper")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--batch", type=Path, help="Batch directory with manifest.jsonl")
    src.add_argument("--scan", type=Path, help="Scan results root and auto-pair runs")
    parser.add_argument("--out", type=Path, default=ROOT / "paper_tables", help="Output directory")
    parser.add_argument(
        "--format",
        nargs="+",
        choices=["md", "latex", "csv"],
        default=["md", "latex", "csv"],
    )
    parser.add_argument("--title", default="EuRoC: baseline vs adaptive")
    args = parser.parse_args()

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
    args.out.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []

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
