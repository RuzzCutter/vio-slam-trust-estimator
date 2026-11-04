#!/usr/bin/env python3
"""Detector quality of the IMU-vision mismatch d(t) on the stale-frame stand.

Uses runs logged with the gate disabled (trust_imu_vis_skip: false), so d is an
open-loop statistic: the reaction does not feed back into the trajectory.
d is recomputed as dR_rad/(flow_med_px+1) for every run, so logs written with the
earlier max(freeze, lag) rule are comparable with the freeze-only ones.

Examples:
  python3 scripts/analyze_imu_vis_detector.py
  python3 scripts/analyze_imu_vis_detector.py --d-thr 0.004941 --out paper_tables/v11_detector
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("matplotlib required: pip install matplotlib") from exc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from degrade_ros2_bag import stale_in_window  # noqa: E402

RESULTS = ROOT / "datasets" / "results"
DEFAULT_OUT = ROOT / "paper_tables" / "v11_detector"

# MH_04 first image timestamp; the stand counts window phase from it.
DEFAULT_BAG_T0 = 1403638127.3298728
DEFAULT_W = 4.0
DEFAULT_PERIOD = 10.0
DEFAULT_AFTER = 30.0
DEFAULT_D_THR = 0.0049411215

DEFAULT_CLEAN = [
    "MH_04_difficult_adaptive_20260910_101233",
    "MH_04_difficult_adaptive_20260910_101424",
    "MH_04_difficult_adaptive_20260910_212157",
    "MH_04_difficult_adaptive_20260910_212347",
]
DEFAULT_STALE = [
    "MH_04_difficult_adaptive_stale_4_after_30_20260910_101614",
    "MH_04_difficult_adaptive_stale_4_after_30_20260910_101805",
    "MH_04_difficult_adaptive_stale_4_after_30_20260910_212537",
    "MH_04_difficult_adaptive_stale_4_after_30_20260910_212728",
]


def load_run(path: Path) -> dict[str, np.ndarray]:
    log = path / "imu_vis.csv" if path.is_dir() else path
    ts: list[float] = []
    dv: list[float] = []
    rot: list[float] = []
    flows: list[float] = []
    for row in csv.DictReader(log.open(encoding="utf-8", newline="")):
        try:
            t = float(row["timestamp"])
            dr = float(row["dR_rad"])
            flow = float(row["flow_med_px"])
        except (KeyError, TypeError, ValueError):
            continue
        ts.append(t)
        dv.append(dr / (flow + 1.0))
        rot.append(dr)
        flows.append(flow)
    if not ts:
        raise SystemExit(f"No usable rows in {log}")
    return {
        "t": np.asarray(ts),
        "d": np.asarray(dv),
        "dR": np.asarray(rot),
        "flow": np.asarray(flows),
    }


def gate_flag(path: Path) -> str:
    cfg = path / "estimator_config.yaml"
    if not cfg.is_file():
        return "?"
    for line in cfg.read_text(encoding="utf-8").splitlines():
        if line.startswith("trust_imu_vis_skip:"):
            return line.split(":", 1)[1].strip()
    return "?"


def window_mask(ts: np.ndarray, bag_t0: float, w: float, period: float, after: float) -> np.ndarray:
    return np.asarray([stale_in_window(float(t), bag_t0, w, period, after_s=after) for t in ts])


def window_index(ts: np.ndarray, bag_t0: float, period: float, after: float) -> np.ndarray:
    return np.floor((ts - (bag_t0 + after)) / period).astype(int)


def roc_curve(pos: np.ndarray, neg: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    scores = np.concatenate([pos, neg])
    labels = np.concatenate([np.ones(pos.size), np.zeros(neg.size)])
    order = np.argsort(-scores, kind="mergesort")
    labels = labels[order]
    scores = scores[order]
    tps = np.cumsum(labels)
    fps = np.cumsum(1.0 - labels)
    keep = np.r_[np.flatnonzero(np.diff(scores)), scores.size - 1]
    tpr = np.r_[0.0, tps[keep] / pos.size]
    fpr = np.r_[0.0, fps[keep] / neg.size]
    return fpr, tpr, float(np.trapezoid(tpr, fpr))


def pctl(values: np.ndarray, q: float) -> float | None:
    return float(np.quantile(values, q)) if values.size else None


def per_window_stats(
    runs: list[tuple[str, dict[str, np.ndarray]]],
    *,
    bag_t0: float,
    w: float,
    period: float,
    after: float,
    d_thr: float,
) -> dict[str, Any]:
    latencies: list[float] = []
    windows: list[dict[str, Any]] = []
    for name, data in runs:
        in_win = window_mask(data["t"], bag_t0, w, period, after)
        if not in_win.any():
            continue
        idx = window_index(data["t"], bag_t0, period, after)
        for k in np.unique(idx[in_win]):
            sel = in_win & (idx == k)
            hits = data["d"][sel] > d_thr
            t_start = bag_t0 + after + float(k) * period
            record = {
                "run": name,
                "k": int(k),
                "frames": int(sel.sum()),
                "dR_med_rad": float(np.median(data["dR"][sel])),
                "d_med": float(np.median(data["d"][sel])),
                "detected": bool(hits.any()),
            }
            if hits.any():
                latencies.append(float(data["t"][sel][hits][0]) - t_start)
            windows.append(record)
    lat = np.asarray(latencies)
    detected = [win for win in windows if win["detected"]]
    missed = [win for win in windows if not win["detected"]]
    return {
        "n_windows": len(windows),
        "n_detected": len(detected),
        "window_detection_rate": (len(detected) / len(windows)) if windows else None,
        "latency_median_s": pctl(lat, 0.50),
        "latency_p90_s": pctl(lat, 0.90),
        "latency_max_s": float(lat.max()) if lat.size else None,
        "dR_med_detected": float(np.median([win["dR_med_rad"] for win in detected])) if detected else None,
        "dR_med_missed": float(np.median([win["dR_med_rad"] for win in missed])) if missed else None,
        "missed_windows": missed,
    }


def plot_hist(clean: np.ndarray, lie: np.ndarray, live: np.ndarray, d_thr: float, out: Path) -> None:
    lo = max(1e-5, min(clean.min(), lie.min(), live.min()))
    hi = max(clean.max(), lie.max(), live.max())
    bins = np.logspace(np.log10(lo), np.log10(hi), 60)
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.hist(clean, bins=bins, alpha=0.65, label="чистые прогоны", density=True)
    ax.hist(live, bins=bins, alpha=0.55, label="живые кадры прогонов с отказом", density=True)
    ax.hist(lie, bins=bins, alpha=0.65, label="окна устаревшего кадра", density=True)
    ax.axvline(d_thr, color="k", linestyle="--", linewidth=1.2, label=f"порог {d_thr:.4f}")
    ax.set_xscale("log")
    ax.set_xlabel("d(t)")
    ax.set_ylabel("плотность")
    ax.legend(fontsize=8)
    ax.set_title("Распределение межсенсорного рассогласования d(t)")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def plot_roc(fpr: np.ndarray, tpr: np.ndarray, auc: float, op: tuple[float, float], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    ax.plot(fpr, tpr, linewidth=1.8, label=f"d(t), AUC = {auc:.3f}")
    ax.plot([0, 1], [0, 1], color="gray", linestyle=":", linewidth=1.0, label="случайный выбор")
    ax.plot([op[0]], [op[1]], "o", color="crimson", markersize=6, label="рабочая точка")
    ax.set_xlabel("доля ложных срабатываний")
    ax.set_ylabel("доля обнаруженных кадров")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.legend(fontsize=8, loc="lower right")
    ax.set_title("ROC детектора устаревшего кадра")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def plot_timeline(
    data: dict[str, np.ndarray],
    *,
    bag_t0: float,
    w: float,
    period: float,
    after: float,
    d_thr: float,
    out: Path,
) -> None:
    rel = data["t"] - bag_t0
    fig, ax = plt.subplots(figsize=(8.0, 3.6))
    span = float(rel.max())
    k = 0
    while after + k * period < span:
        start = after + k * period
        ax.axvspan(start, min(start + w, span), color="tab:orange", alpha=0.18,
                   label="окно устаревшего кадра" if k == 0 else None)
        k += 1
    ax.plot(rel, data["d"], linewidth=0.8, color="tab:blue", label="d(t)")
    ax.axhline(d_thr, color="k", linestyle="--", linewidth=1.0, label=f"порог {d_thr:.4f}")
    ax.set_yscale("log")
    ax.set_xlabel("время от первого кадра, с")
    ax.set_ylabel("d(t)")
    ax.legend(fontsize=8, loc="upper right")
    ax.set_title("Межсенсорное рассогласование во времени (прогон с отказом)")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fmt(value: float | None, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def write_table(summary: dict[str, Any], path: Path) -> None:
    d = summary["pooled"]
    op = summary["operating_point"]
    win = summary["per_window"]
    lines = [
        "## Детектор устаревшего кадра по d(t) (гейт выключен)",
        "",
        f"Прогоны: {summary['n_runs_clean']} чистых, {summary['n_runs_stale']} с отказом; "
        f"стенд W={summary['stand']['W']} с, период {summary['stand']['period']} с, начало {summary['stand']['after']} с.",
        "",
        "| Выборка | Кадров | Медиана d | p90 d |",
        "|---------|--------|-----------|-------|",
        f"| Чистые прогоны | {d['n_clean']} | {fmt(d['clean_p50'])} | {fmt(d['clean_p90'])} |",
        f"| Живые кадры прогонов с отказом | {d['n_live']} | {fmt(d['live_p50'])} | {fmt(d['live_p90'])} |",
        f"| Окна устаревшего кадра | {d['n_lie']} | {fmt(d['lie_p50'])} | {fmt(d['lie_p90'])} |",
        "",
        f"Отношение медиан «окна / чистые»: {fmt(d['ratio_lie_clean'], 2)}.",
        "",
        "| Показатель | Значение |",
        "|------------|----------|",
        f"| AUC (окна против чистых прогонов) | {fmt(summary['auc_vs_clean'], 3)} |",
        f"| AUC (окна против живых кадров тех же прогонов) | {fmt(summary['auc_vs_live'], 3)} |",
        f"| Порог d_thr | {fmt(op['d_thr'])} |",
        f"| Доля обнаруженных кадров в окнах | {fmt(op['tpr'], 3)} |",
        f"| Доля ложных срабатываний на чистых прогонах | {fmt(op['fpr_clean'], 5)} |",
        f"| Доля ложных срабатываний на живых кадрах | {fmt(op['fpr_live'], 5)} |",
        f"| Обнаружено окон | {win['n_detected']} из {win['n_windows']} |",
        f"| Задержка обнаружения, медиана | {fmt(win['latency_median_s'], 3)} с |",
        f"| Задержка обнаружения, p90 | {fmt(win['latency_p90_s'], 3)} с |",
        "",
        f"Медиана |Δθ| в обнаруженных окнах {fmt(win['dR_med_detected'], 5)} рад, "
        f"в необнаруженных {fmt(win['dR_med_missed'], 5)} рад: признак наблюдаем только при вращении носителя.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", nargs="*", default=DEFAULT_CLEAN, help="Clean run dirs (names under datasets/results or paths)")
    parser.add_argument("--stale", nargs="*", default=DEFAULT_STALE, help="Stale-stand run dirs")
    parser.add_argument("--bag-t0", type=float, default=DEFAULT_BAG_T0)
    parser.add_argument("--stale-w", type=float, default=DEFAULT_W)
    parser.add_argument("--period", type=float, default=DEFAULT_PERIOD)
    parser.add_argument("--after", type=float, default=DEFAULT_AFTER)
    parser.add_argument("--d-thr", type=float, default=DEFAULT_D_THR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    def resolve(name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() or p.exists() else RESULTS / name

    clean_runs = [(n, load_run(resolve(n))) for n in args.clean]
    stale_runs = [(n, load_run(resolve(n))) for n in args.stale]

    gates = {n: gate_flag(resolve(n)) for n, _ in clean_runs + stale_runs}
    closed = sorted(n for n, flag in gates.items() if flag != "false")
    if closed:
        print(f"WARNING: gate not disabled in {len(closed)} run(s): {', '.join(closed)}", file=sys.stderr)

    clean_d = np.concatenate([data["d"] for _, data in clean_runs])
    lie_parts: list[np.ndarray] = []
    live_parts: list[np.ndarray] = []
    for _, data in stale_runs:
        in_win = window_mask(data["t"], args.bag_t0, args.stale_w, args.period, args.after)
        lie_parts.append(data["d"][in_win])
        live_parts.append(data["d"][~in_win])
    lie_d = np.concatenate(lie_parts)
    live_d = np.concatenate(live_parts)

    fpr, tpr, auc_clean = roc_curve(lie_d, clean_d)
    _, _, auc_live = roc_curve(lie_d, live_d)

    op_tpr = float(np.mean(lie_d > args.d_thr))
    op_fpr_clean = float(np.mean(clean_d > args.d_thr))
    op_fpr_live = float(np.mean(live_d > args.d_thr))

    win = per_window_stats(
        stale_runs,
        bag_t0=args.bag_t0,
        w=args.stale_w,
        period=args.period,
        after=args.after,
        d_thr=args.d_thr,
    )

    clean_p50 = pctl(clean_d, 0.50)
    lie_p50 = pctl(lie_d, 0.50)
    summary: dict[str, Any] = {
        "runs_clean": [n for n, _ in clean_runs],
        "runs_stale": [n for n, _ in stale_runs],
        "n_runs_clean": len(clean_runs),
        "n_runs_stale": len(stale_runs),
        "gate_flags": gates,
        "stand": {"W": args.stale_w, "period": args.period, "after": args.after, "bag_t0": args.bag_t0},
        "pooled": {
            "n_clean": int(clean_d.size),
            "n_live": int(live_d.size),
            "n_lie": int(lie_d.size),
            "clean_p50": clean_p50,
            "clean_p90": pctl(clean_d, 0.90),
            "live_p50": pctl(live_d, 0.50),
            "live_p90": pctl(live_d, 0.90),
            "lie_p50": lie_p50,
            "lie_p90": pctl(lie_d, 0.90),
            "ratio_lie_clean": (lie_p50 / clean_p50) if clean_p50 else None,
        },
        "auc_vs_clean": auc_clean,
        "auc_vs_live": auc_live,
        "operating_point": {
            "d_thr": args.d_thr,
            "tpr": op_tpr,
            "fpr_clean": op_fpr_clean,
            "fpr_live": op_fpr_live,
        },
        "per_window": win,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_table(summary, args.out / "table_detector.md")
    plot_hist(clean_d, lie_d, live_d, args.d_thr, args.out / "d_hist.png")
    plot_roc(fpr, tpr, auc_clean, (op_fpr_clean, op_tpr), args.out / "d_roc.png")
    plot_timeline(
        stale_runs[-1][1],
        bag_t0=args.bag_t0,
        w=args.stale_w,
        period=args.period,
        after=args.after,
        d_thr=args.d_thr,
        out=args.out / "d_timeline.png",
    )

    print(f"clean n={clean_d.size} med={fmt(clean_p50)}  lie n={lie_d.size} med={fmt(lie_p50)} "
          f"ratio={fmt(summary['pooled']['ratio_lie_clean'], 2)}")
    print(f"AUC vs clean={auc_clean:.4f}  vs live={auc_live:.4f}")
    print(f"at d_thr={args.d_thr}: TPR={op_tpr:.4f}  FPR_clean={op_fpr_clean:.5f}  FPR_live={op_fpr_live:.5f}")
    print(f"windows detected {win['n_detected']}/{win['n_windows']}  latency med={fmt(win['latency_median_s'], 3)} s")
    print(f"median |dR| detected={fmt(win['dR_med_detected'], 5)} rad  missed={fmt(win['dR_med_missed'], 5)} rad")
    print(f"artifacts: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
