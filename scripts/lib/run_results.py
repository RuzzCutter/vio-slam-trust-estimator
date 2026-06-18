#!/usr/bin/env python3
"""Load experiment run directories, pair compare results, export paper tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
TRAJ_STATS = ROOT / "scripts" / "traj_stats.py"

DIR_RE = re.compile(
    r"^(?P<seq>.+)_(?P<mode>baseline|adaptive)"
    r"(?:_(?P<degrade_tag>gaussian_\d+|brightness_\d+))?"
    r"_(?P<ts>\d{8}_\d{6})(?:_retry(?P<retry>\d+))?$"
)


def degrade_tag_to_spec(tag: str | None) -> str:
    if not tag:
        return ""
    if tag.startswith("gaussian_"):
        return f"gaussian:{tag.split('_', 1)[1]}"
    if tag.startswith("brightness_"):
        return f"brightness:{tag.split('_', 1)[1]}"
    return tag.replace("_", ":")


def degrade_spec_to_label(spec: str) -> str:
    if not spec:
        return "clean"
    kind, _, level = spec.partition(":")
    labels = {"gaussian": "D1 blur", "brightness": "D3 bright"}
    return f"{labels.get(kind, kind)} σ={level}" if kind == "gaussian" else f"{labels.get(kind, kind)} +{level}%"


def _read_key_value(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _parse_float(value: str | None) -> float | None:
    if value is None or value in ("", "nan", "n/a", "None"):
        return None
    try:
        v = float(value)
        return None if math.isnan(v) else v
    except ValueError:
        return None


def _traj_stats(traj: Path) -> dict[str, Any]:
    if not traj.is_file():
        return {"diverged": True, "poses": 0}
    try:
        proc = subprocess.run(
            [sys.executable, str(TRAJ_STATS), str(traj)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {"diverged": True, "poses": 0}
    stats: dict[str, Any] = {"diverged": True, "poses": 0}
    if proc.returncode != 0 and not proc.stdout.strip():
        return stats
    for token in proc.stdout.strip().split():
        if "=" in token:
            k, v = token.split("=", 1)
            if k in ("poses", "diverged"):
                stats[k] = int(float(v))
            elif k.endswith("_m"):
                stats[k] = float(v)
    return stats


def _trust_summary(trust_log: Path) -> dict[str, float | None]:
    if not trust_log.is_file():
        return {"c_mean": None, "trust_rows": 0}
    rows = 0
    c_sum = 0.0
    with trust_log.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            c_val = row.get("c")
            if c_val is None:
                continue
            try:
                c_sum += float(c_val)
                rows += 1
            except ValueError:
                continue
    return {
        "c_mean": (c_sum / rows) if rows else None,
        "trust_rows": rows,
    }


@dataclass
class RunRecord:
    result_dir: str
    seq: str
    mode: str
    degrade: str = ""
    degrade_label: str = "clean"
    timestamp: str = ""
    retry: int = 0
    ape_rmse_m: float | None = None
    rpe_rmse_m: float | None = None
    poses: int = 0
    path_m: float | None = None
    span_m: float | None = None
    diverged: bool = False
    c_mean: float | None = None
    trust_rows: int = 0
    has_gt: bool = False
    init_ok: bool = False

    @property
    def tracking_failure(self) -> bool:
        return self.diverged or self.poses < 2 or not self.init_ok


@dataclass
class CompareRecord:
    seq: str
    degrade: str = ""
    degrade_label: str = "clean"
    baseline: RunRecord | None = None
    adaptive: RunRecord | None = None
    batch_id: str = ""
    run_index: int = 0
    finished_at: str = ""

    def delta_ape_pct(self) -> float | None:
        b, a = self.baseline, self.adaptive
        if not b or not a or b.ape_rmse_m is None or a.ape_rmse_m is None or b.ape_rmse_m <= 0:
            return None
        return (a.ape_rmse_m / b.ape_rmse_m - 1.0) * 100.0

    def verdict(self) -> str:
        b, a = self.baseline, self.adaptive
        if not b or not a or b.ape_rmse_m is None or a.ape_rmse_m is None:
            return "no_metrics"
        degraded = bool(self.degrade)
        ratio = a.ape_rmse_m / b.ape_rmse_m if b.ape_rmse_m > 0 else float("inf")
        if degraded:
            if ratio < 0.9:
                return "confirmed"
            if ratio <= 1.05:
                return "neutral"
            return "worse"
        if ratio <= 1.05 and ratio >= 0.95:
            return "similar"
        if ratio < 0.9:
            return "unexpected_better"
        if ratio > 1.05:
            return "worse"
        return "similar"


def parse_result_dirname(name: str) -> dict[str, Any] | None:
    m = DIR_RE.match(name)
    if not m:
        return None
    degrade_tag = m.group("degrade_tag")
    return {
        "seq": m.group("seq"),
        "mode": m.group("mode"),
        "degrade_tag": degrade_tag,
        "degrade": degrade_tag_to_spec(degrade_tag),
        "timestamp": m.group("ts"),
        "retry": int(m.group("retry") or 0),
    }


def load_run_record(result_dir: Path | str) -> RunRecord:
    path = Path(result_dir).resolve()
    meta_path = path / "run_meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rec = RunRecord(
            result_dir=str(path),
            seq=meta.get("seq", ""),
            mode=meta.get("mode", ""),
            degrade=meta.get("degrade", ""),
            degrade_label=degrade_spec_to_label(meta.get("degrade", "")),
            timestamp=meta.get("timestamp", ""),
            retry=int(meta.get("retry", 0)),
            ape_rmse_m=_parse_float(str(meta.get("ape_rmse_m"))) if meta.get("ape_rmse_m") is not None else None,
            rpe_rmse_m=_parse_float(str(meta.get("rpe_rmse_m"))) if meta.get("rpe_rmse_m") is not None else None,
            poses=int(meta.get("poses", 0)),
            path_m=_parse_float(str(meta.get("path_m"))) if meta.get("path_m") is not None else None,
            span_m=_parse_float(str(meta.get("span_m"))) if meta.get("span_m") is not None else None,
            diverged=bool(meta.get("diverged", False)),
            c_mean=_parse_float(str(meta.get("c_mean"))) if meta.get("c_mean") is not None else None,
            trust_rows=int(meta.get("trust_rows", 0)),
            has_gt=bool(meta.get("has_gt", False)),
            init_ok=bool(meta.get("init_ok", False)),
        )
        return rec

    parsed = parse_result_dirname(path.name)
    if not parsed:
        parsed = {"seq": path.name, "mode": "unknown", "degrade": "", "timestamp": "", "retry": 0}

    summary = _read_key_value(path / "metrics" / "summary.txt")
    traj = path / "trajectory_tum.txt"
    stats = _traj_stats(traj)
    trust = _trust_summary(path / "trust_log.csv")
    log = path / "openvins.log"
    init_ok = log.is_file() and "successful initialization" in log.read_text(encoding="utf-8", errors="replace")

    degrade = parsed.get("degrade", "")
    return RunRecord(
        result_dir=str(path),
        seq=parsed["seq"],
        mode=parsed["mode"],
        degrade=degrade,
        degrade_label=degrade_spec_to_label(degrade),
        timestamp=parsed.get("timestamp", ""),
        retry=int(parsed.get("retry", 0)),
        ape_rmse_m=_parse_float(summary.get("ape_rmse_m")),
        rpe_rmse_m=_parse_float(summary.get("rpe_rmse_m")),
        poses=int(stats.get("poses", 0)),
        path_m=stats.get("path_m"),
        span_m=stats.get("span_m"),
        diverged=bool(stats.get("diverged", 0)),
        c_mean=trust.get("c_mean"),
        trust_rows=int(trust.get("trust_rows", 0)),
        has_gt=(path / "metrics" / "summary.txt").is_file(),
        init_ok=init_ok,
    )


def write_run_meta(
    out_dir: Path,
    *,
    seq: str,
    mode: str,
    degrade: str = "",
    start_offset: int | None = None,
    trust_tau: float | None = None,
    retry: int = 0,
) -> Path:
    out_dir = out_dir.resolve()
    rec = load_run_record(out_dir)
    meta = {
        "seq": seq,
        "mode": mode,
        "degrade": degrade,
        "degrade_label": degrade_spec_to_label(degrade),
        "timestamp": parse_result_dirname(out_dir.name) or {},
        "start_offset": start_offset,
        "trust_tau": trust_tau,
        "retry": retry,
        "result_dir": str(out_dir),
        "ape_rmse_m": rec.ape_rmse_m,
        "rpe_rmse_m": rec.rpe_rmse_m,
        "poses": rec.poses,
        "path_m": rec.path_m,
        "span_m": rec.span_m,
        "diverged": rec.diverged,
        "c_mean": rec.c_mean,
        "trust_rows": rec.trust_rows,
        "has_gt": rec.has_gt,
        "init_ok": rec.init_ok,
        "written_at": datetime.now().isoformat(timespec="seconds"),
    }
    ts = parse_result_dirname(out_dir.name)
    if ts:
        meta["timestamp"] = ts["timestamp"]
    path = out_dir / "run_meta.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def compare_from_dirs(baseline_dir: Path | str, adaptive_dir: Path | str, **kwargs: Any) -> CompareRecord:
    baseline = load_run_record(baseline_dir)
    adaptive = load_run_record(adaptive_dir)
    degrade = baseline.degrade or adaptive.degrade
    return CompareRecord(
        seq=baseline.seq or adaptive.seq,
        degrade=degrade,
        degrade_label=degrade_spec_to_label(degrade),
        baseline=baseline,
        adaptive=adaptive,
        **kwargs,
    )


def _pair_key(rec: RunRecord) -> tuple[str, str, str]:
    return rec.seq, rec.degrade, rec.timestamp[:8] if rec.timestamp else ""


def scan_results_root(results_root: Path) -> list[CompareRecord]:
    """Pair baseline/adaptive dirs by seq+degrade and closest timestamps (baseline first)."""
    runs: list[RunRecord] = []
    for child in sorted(results_root.iterdir()):
        if not child.is_dir() or child.name == "batches":
            continue
        if parse_result_dirname(child.name) is None and not (child / "run_meta.json").is_file():
            continue
        runs.append(load_run_record(child))

    baselines = [r for r in runs if r.mode == "baseline"]
    adaptives = [r for r in runs if r.mode == "adaptive"]
    pairs: list[CompareRecord] = []
    used: set[str] = set()

    for b in sorted(baselines, key=lambda r: r.timestamp):
        best: RunRecord | None = None
        best_dt = 10**9
        for a in adaptives:
            if a.result_dir in used:
                continue
            if a.seq != b.seq or a.degrade != b.degrade:
                continue
            if not b.timestamp or not a.timestamp:
                continue
            tb = datetime.strptime(b.timestamp, "%Y%m%d_%H%M%S")
            ta = datetime.strptime(a.timestamp, "%Y%m%d_%H%M%S")
            dt = (ta - tb).total_seconds()
            if dt < 0 or dt > 7200:
                continue
            if dt < best_dt:
                best_dt = dt
                best = a
        if best:
            used.add(best.result_dir)
            pairs.append(compare_from_dirs(b.result_dir, best.result_dir))
    return pairs


def load_batch_manifest(batch_dir: Path) -> list[CompareRecord]:
    batch_dir = batch_dir.resolve()
    records: list[CompareRecord] = []
    manifest = batch_dir / "manifest.jsonl"
    if not manifest.is_file():
        return records
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        baseline_dir = row.get("baseline_dir")
        adaptive_dir = row.get("adaptive_dir")
        if not baseline_dir or not adaptive_dir:
            continue
        records.append(
            compare_from_dirs(
                baseline_dir,
                adaptive_dir,
                batch_id=batch_dir.name,
                run_index=int(row.get("index", 0)),
                finished_at=row.get("finished_at", ""),
            )
        )
    return records


def fmt_m(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


VERDICT_RU = {
    "confirmed": "подтверждена",
    "neutral": "нейтрально",
    "similar": "≈ baseline",
    "unexpected_better": "лучше на clean",
    "worse": "хуже",
    "no_metrics": "нет метрик",
}


def render_markdown_table(rows: list[CompareRecord], *, title: str = "") -> str:
    lines: list[str] = []
    if title:
        lines.extend([f"## {title}", ""])
    lines.append(
        "| Seq | Условие | ATE base [m] | ATE adapt [m] | ΔATE | RPE base [m] | RPE adapt [m] | c̄ | Fail | Вердикт |"
    )
    lines.append("|-----|---------|--------------|---------------|------|--------------|---------------|-----|------|---------|")
    for row in rows:
        b, a = row.baseline, row.adaptive
        fail = "да" if (b and b.tracking_failure) or (a and a.tracking_failure) else "нет"
        lines.append(
            "| {seq} | {cond} | {bate} | {aate} | {d} | {brpe} | {arpe} | {c} | {fail} | {v} |".format(
                seq=row.seq,
                cond=row.degrade_label,
                bate=fmt_m(b.ape_rmse_m if b else None),
                aate=fmt_m(a.ape_rmse_m if a else None),
                d=fmt_pct(row.delta_ape_pct()),
                brpe=fmt_m(b.rpe_rmse_m if b else None),
                arpe=fmt_m(a.rpe_rmse_m if a else None),
                c=fmt_m(a.c_mean if a else None, 3),
                fail=fail,
                v=VERDICT_RU.get(row.verdict(), row.verdict()),
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_latex_table(rows: list[CompareRecord], *, caption: str = "", label: str = "tab:ate") -> str:
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\begin{tabular}{llrrrrrr}",
        "\\hline",
        "Seq & Cond. & ATE$_b$ & ATE$_a$ & $\\Delta$ATE & RPE$_b$ & RPE$_a$ & $\\bar{c}$ \\\\",
        "\\hline",
    ]
    for row in rows:
        b, a = row.baseline, row.adaptive
        lines.append(
            f"{row.seq.replace('_', '\\_')} & {row.degrade_label} & "
            f"{fmt_m(b.ape_rmse_m if b else None)} & {fmt_m(a.ape_rmse_m if a else None)} & "
            f"{fmt_pct(row.delta_ape_pct())} & {fmt_m(b.rpe_rmse_m if b else None)} & "
            f"{fmt_m(a.rpe_rmse_m if a else None)} & {fmt_m(a.c_mean if a else None)} \\\\"
        )
    lines.extend(["\\hline", "\\end{tabular}"])
    if caption:
        lines.append(f"\\caption{{{caption}}}")
    lines.append(f"\\label{{{label}}}")
    lines.append("\\end{table}")
    lines.append("")
    return "\n".join(lines)


def render_csv(rows: list[CompareRecord]) -> str:
    buf: list[str] = []
    import io

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "seq", "degrade", "degrade_label",
        "baseline_dir", "adaptive_dir",
        "ape_baseline_m", "ape_adaptive_m", "delta_ape_pct",
        "rpe_baseline_m", "rpe_adaptive_m",
        "c_mean", "baseline_diverged", "adaptive_diverged",
        "verdict", "batch_id", "run_index",
    ])
    for row in rows:
        b, a = row.baseline, row.adaptive
        writer.writerow([
            row.seq,
            row.degrade,
            row.degrade_label,
            b.result_dir if b else "",
            a.result_dir if a else "",
            b.ape_rmse_m if b else "",
            a.ape_rmse_m if a else "",
            row.delta_ape_pct() if row.delta_ape_pct() is not None else "",
            b.rpe_rmse_m if b else "",
            a.rpe_rmse_m if a else "",
            a.c_mean if a else "",
            b.diverged if b else "",
            a.diverged if a else "",
            row.verdict(),
            row.batch_id,
            row.run_index,
        ])
    return out.getvalue()


def split_clean_degraded(rows: list[CompareRecord]) -> tuple[list[CompareRecord], list[CompareRecord]]:
    clean = [r for r in rows if not r.degrade]
    degraded = [r for r in rows if r.degrade]
    return clean, degraded


def cmd_write_meta(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--seq", required=True)
    p.add_argument("--mode", choices=["baseline", "adaptive"], required=True)
    p.add_argument("--degrade", default="")
    p.add_argument("--start-offset", type=int, default=None)
    p.add_argument("--trust-tau", type=float, default=None)
    p.add_argument("--retry", type=int, default=0)
    args = p.parse_args(argv)
    write_run_meta(
        args.dir,
        seq=args.seq,
        mode=args.mode,
        degrade=args.degrade,
        start_offset=args.start_offset,
        trust_tau=args.trust_tau,
        retry=args.retry,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv and argv[0] == "write-meta":
        return cmd_write_meta(argv[1:])
    parser = argparse.ArgumentParser(description="Inspect run result directories")
    parser.add_argument("dirs", nargs="*", type=Path, help="Result directories")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    for d in args.dirs:
        rec = load_run_record(d)
        if args.json:
            print(json.dumps(asdict(rec), ensure_ascii=False, indent=2))
        else:
            print(f"{d.name}: APE={fmt_m(rec.ape_rmse_m)} diverged={rec.diverged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
