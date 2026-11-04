#!/usr/bin/env python3
"""Unit tests for stage A (repeats, stats, ablation full, correlation). No OpenVINS runs."""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import run_batch  # noqa: E402
from correlate_trust_ate import correlate_run  # noqa: E402
from evaluate_trajectory import export_pose_errors  # noqa: E402
from repeat_stats import (  # noqa: E402
    PAIR_TTEST_MIN_N,
    aggregate_compare,
    attach_compare_full,
    bootstrap_mean_diff_ci,
    ci_contains_zero,
    paired_ttest_p,
    wilcoxon_signed_rank_p,
)
from run_results import (  # noqa: E402
    AblationGroup,
    CompareRecord,
    RunRecord,
    load_batch_manifest,
)


def _run(**kwargs: object) -> RunRecord:
    data = dict(
        result_dir="/tmp/fake",
        seq="MH_04_difficult",
        mode="adaptive",
        degrade="",
        ape_rmse_m=0.4,
        rpe_rmse_m=0.1,
        poses=100,
        init_ok=True,
        diverged=False,
        c_mean=0.64,
        max_gap_s=0.05,
        max_coord_m=2.0,
        has_gt=True,
    )
    data.update(kwargs)
    return RunRecord(**data)  # type: ignore[arg-type]


class TestExpandJobs(unittest.TestCase):
    def test_paper_plan_90_jobs(self) -> None:
        plan = run_batch.load_plan(ROOT / "config" / "batch_paper.yaml")
        jobs = run_batch.expand_jobs(plan)
        self.assertEqual(len(plan["runs"]), 10)
        self.assertEqual(plan["repeats"], 9)
        self.assertEqual(len(jobs), 90)
        self.assertEqual(jobs[0]["repeat"], 1)
        self.assertEqual(jobs[8]["repeat"], 9)
        self.assertEqual(jobs[9]["seq"], "MH_05_difficult")
        for job in jobs:
            self.assertNotIn("start_offset", job)

    def test_ablation_plan_no_full(self) -> None:
        plan = run_batch.load_plan(ROOT / "config" / "batch_ablation.yaml")
        jobs = run_batch.expand_jobs(plan)
        self.assertEqual(plan["repeats"], 7)
        self.assertEqual(len(plan["runs"]), 16)
        self.assertEqual(len(jobs), 112)
        self.assertTrue(all(j.get("ablate") for j in jobs))

    def test_smoke_two_jobs(self) -> None:
        plan = run_batch.load_plan(ROOT / "config" / "batch_smoke.yaml")
        jobs = run_batch.expand_jobs(plan)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["seq"], jobs[1]["seq"])
        self.assertEqual([j["repeat"] for j in jobs], [1, 2])

    def test_cli_repeats_override(self) -> None:
        plan = run_batch.load_plan(ROOT / "config" / "batch_paper.yaml")
        jobs = run_batch.expand_jobs(plan, repeats=2)
        self.assertEqual(len(jobs), 20)

    def test_select_compare_dirs_uses_retry(self) -> None:
        dirs = [
            "/tmp/MH_01_easy_baseline_20260825_092934",
            "/tmp/MH_01_easy_adaptive_20260825_093056",
            "/tmp/MH_01_easy_adaptive_20260825_093056_retry2",
        ]
        base, adapt = run_batch.select_compare_dirs(dirs)
        self.assertTrue(base and base.endswith("092934"))
        self.assertTrue(adapt and adapt.endswith("_retry2"))


class TestProtocolAndStats(unittest.TestCase):
    def test_gap_is_protocol_fail(self) -> None:
        rec = _run(max_gap_s=0.8, ape_rmse_m=0.3)
        self.assertTrue(rec.protocol_failure)
        self.assertFalse(rec.is_success)

    def test_missing_ate_is_fail(self) -> None:
        rec = _run(ape_rmse_m=None)
        self.assertTrue(rec.protocol_failure)

    def test_success_pair_stats(self) -> None:
        jobs: list[CompareRecord] = []
        base = [1.0, 1.1, 1.2, 1.3, 1.4]
        adapt = [0.50, 0.55, 0.60, 0.65, 0.70]
        for i, (b, a) in enumerate(zip(base, adapt), start=1):
            jobs.append(
                CompareRecord(
                    seq="MH_04_difficult",
                    degrade="gaussian:5",
                    degrade_label="D1 blur σ=5",
                    baseline=_run(mode="baseline", ape_rmse_m=b),
                    adaptive=_run(mode="adaptive", ape_rmse_m=a),
                    repeat=i,
                )
            )
        jobs.append(
            CompareRecord(
                seq="MH_04_difficult",
                degrade="gaussian:5",
                degrade_label="D1 blur σ=5",
                baseline=_run(mode="baseline", ape_rmse_m=None, init_ok=False, poses=0),
                adaptive=_run(mode="adaptive", ape_rmse_m=None, init_ok=False, poses=0),
                repeat=6,
                status="failed",
            )
        )
        cells = aggregate_compare(jobs)
        self.assertEqual(len(cells), 1)
        cell = cells[0]
        self.assertEqual(cell.n_launch, 6)
        self.assertEqual(cell.n_success, 5)
        self.assertEqual(cell.n_fail, 1)
        self.assertAlmostEqual(cell.ate_stats("baseline").median or 0, 1.2)
        self.assertAlmostEqual(cell.ate_stats("adaptive").median or 0, 0.6)
        delta = cell.delta_ate_pct_medians()
        self.assertIsNotNone(delta)
        self.assertLess(delta or 0, -40)
        self.assertEqual(cell.verdict(), "confirmed")
        p = cell.paired_p()
        self.assertIsNotNone(p)
        self.assertLess(p or 1, 0.05)

    def test_ttest_requires_five_pairs(self) -> None:
        a = [1.0, 1.1, 1.2, 1.3]
        b = [0.9, 1.0, 1.1, 1.2]
        self.assertIsNone(paired_ttest_p(a, b))
        self.assertIsNone(wilcoxon_signed_rank_p(a, b))
        self.assertIsNone(bootstrap_mean_diff_ci(a, b))
        self.assertGreaterEqual(PAIR_TTEST_MIN_N, 5)

    def test_wilcoxon_and_bootstrap_clear_shift(self) -> None:
        base = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6]
        adapt = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
        p_w = wilcoxon_signed_rank_p(base, adapt)
        self.assertIsNotNone(p_w)
        self.assertLess(p_w or 1.0, 0.05)
        ci = bootstrap_mean_diff_ci(base, adapt)
        self.assertIsNotNone(ci)
        assert ci is not None
        lo, hi, mean_d = ci
        self.assertLess(hi, 0.0)
        self.assertLess(mean_d, 0.0)
        self.assertFalse(ci_contains_zero(ci))
        self.assertLess(lo, hi)

    def test_bootstrap_ci_includes_zero_when_no_shift(self) -> None:
        base = [0.40, 0.55, 0.38, 0.62, 0.51, 0.44, 0.58]
        adapt = [0.41, 0.53, 0.40, 0.60, 0.50, 0.46, 0.57]
        ci = bootstrap_mean_diff_ci(base, adapt)
        self.assertIsNotNone(ci)
        self.assertTrue(ci_contains_zero(ci))


class TestAblationFullFromCompare(unittest.TestCase):
    def test_full_replaced_by_compare_adaptive(self) -> None:
        compare = [
            CompareRecord(
                seq="MH_04_difficult",
                degrade="gaussian:5",
                adaptive=_run(ape_rmse_m=0.448, result_dir="/tmp/cmp_a"),
                baseline=_run(mode="baseline", ape_rmse_m=1.8),
            ),
            CompareRecord(
                seq="MH_04_difficult",
                degrade="gaussian:5",
                adaptive=_run(ape_rmse_m=0.452, result_dir="/tmp/cmp_b"),
                baseline=_run(mode="baseline", ape_rmse_m=1.7),
            ),
        ]
        group = AblationGroup(seq="MH_04_difficult", degrade="gaussian:5", degrade_label="D1")
        group.variants["full"] = [_run(ape_rmse_m=2.630, result_dir="/tmp/old_full")]
        group.variants["f1"] = [_run(ape_rmse_m=0.445)]
        attach_compare_full([group], compare)
        self.assertEqual(group.full_source, "compare")
        self.assertEqual(group.n_success("full"), 2)
        self.assertAlmostEqual(group.median_ape("full") or 0, 0.45)


class TestPoseErrorsAndCorr(unittest.TestCase):
    def test_export_pose_errors_from_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            est = tmp_path / "est.txt"
            est.write_text("100.0 0 0 0 0 0 0 1\n101.0 1 0 0 0 0 0 1\n", encoding="utf-8")
            ape_zip = tmp_path / "ape.zip"
            errors = np.array([0.11, 0.22], dtype=float)
            seconds = np.array([0.0, 1.0], dtype=float)
            with zipfile.ZipFile(ape_zip, "w") as zf:
                buf = io.BytesIO()
                np.save(buf, errors)
                zf.writestr("error_array.npy", buf.getvalue())
                buf = io.BytesIO()
                np.save(buf, seconds)
                zf.writestr("seconds_from_start.npy", buf.getvalue())
            out = tmp_path / "pose_errors.csv"
            n = export_pose_errors(ape_zip, est, out)
            self.assertEqual(n, 2)
            with out.open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 2)
            self.assertAlmostEqual(float(rows[0]["t"]), 100.0)
            self.assertAlmostEqual(float(rows[1]["e_ate_m"]), 0.22)

    def test_negative_correlation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rd = Path(tmp)
            t = np.linspace(0, 10, 80)
            c = 0.4 + 0.4 * np.sin(t)
            e = 1.0 - c + 0.01 * np.random.default_rng(0).normal(size=t.size)
            (rd / "metrics").mkdir()
            with (rd / "trust_log.csv").open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["timestamp", "f1", "f2", "f3", "f4", "c"])
                for ti, ci in zip(t, c, strict=True):
                    w.writerow([f"{ti:.6f}", 0.5, 0.5, 0.5, 0.5, f"{ci:.6f}"])
            with (rd / "metrics" / "pose_errors.csv").open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["t", "e_ate_m"])
                for ti, ei in zip(t, e, strict=True):
                    w.writerow([f"{ti:.6f}", f"{ei:.6f}"])
            (rd / "run_meta.json").write_text(
                json.dumps(
                    {
                        "seq": "MH_04_difficult",
                        "mode": "adaptive",
                        "degrade": "gaussian:5",
                        "ape_rmse_m": 0.4,
                        "rpe_rmse_m": 0.1,
                        "poses": 80,
                        "init_ok": True,
                        "diverged": False,
                        "c_mean": float(c.mean()),
                        "max_gap_s": 0.13,
                        "max_coord_m": 1.0,
                    }
                ),
                encoding="utf-8",
            )
            corr = correlate_run(rd, window_s=2.0, c_skip=0.15, max_dt=0.2)
            self.assertGreater(corr.n_aligned, 50)
            self.assertIsNotNone(corr.pearson_r)
            self.assertLess(corr.pearson_r or 0, -0.8)
            self.assertGreater(corr.c_p90 or 0, corr.c_p10 or 1)


class TestManifestLoad(unittest.TestCase):
    def test_manifest_keeps_failed_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp)
            (batch / "manifest.jsonl").write_text(
                json.dumps(
                    {
                        "index": 1,
                        "repeat": 1,
                        "seq": "MH_05_difficult",
                        "degrade": "",
                        "status": "failed",
                        "baseline_dir": None,
                        "adaptive_dir": None,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            rows = load_batch_manifest(batch)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "failed")
            self.assertIsNone(rows[0].baseline)


class TestSummarizeTrustMedians(unittest.TestCase):
    def test_median_c_and_noise_scale(self) -> None:
        from summarize_trust import summarize_trust_log

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust_log.csv"
            with path.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(
                    [
                        "timestamp",
                        "f1",
                        "f2",
                        "f3",
                        "f4",
                        "c",
                        "n_features",
                        "n_inliers",
                        "e_repr",
                        "tr_pose",
                        "skip_update",
                        "noise_scale",
                    ]
                )
                for i, (c, s, skip) in enumerate(
                    ((0.4, 1.0, 0), (0.5, 1.2, 0), (0.9, 2.0, 1)),
                    start=1,
                ):
                    w.writerow([i, 0.5, 0.5, 0.5, 0.5, c, 10, 8, 0.1, 0.01, skip, s])
            d = summarize_trust_log(path)
            self.assertEqual(d["n"], 3)
            self.assertAlmostEqual(d["c_p50"] or 0, 0.5)
            self.assertAlmostEqual(d["noise_scale_p50"] or 0, 1.2)
            self.assertAlmostEqual(d["skip_frac"] or 0, 1 / 3)


class TestStaleWindow(unittest.TestCase):
    def test_period_10_window_2(self) -> None:
        from degrade_ros2_bag import stale_in_window

        t0 = 100.0
        self.assertTrue(stale_in_window(100.0, t0, 2.0))
        self.assertTrue(stale_in_window(101.9, t0, 2.0))
        self.assertFalse(stale_in_window(102.0, t0, 2.0))
        self.assertTrue(stale_in_window(110.5, t0, 2.0))
        self.assertFalse(stale_in_window(115.0, t0, 2.0))

    def test_after_30_first_window(self) -> None:
        from degrade_ros2_bag import parse_degrade_spec, stale_in_window

        dtype, level, after_s = parse_degrade_spec("stale:1:after=30")
        self.assertEqual(dtype, "stale")
        self.assertEqual(level, 1.0)
        self.assertEqual(after_s, 30.0)
        t0 = 100.0
        self.assertFalse(stale_in_window(129.9, t0, 1.0, after_s=30.0))
        self.assertTrue(stale_in_window(130.5, t0, 1.0, after_s=30.0))
        self.assertFalse(stale_in_window(131.0, t0, 1.0, after_s=30.0))
        self.assertTrue(stale_in_window(140.2, t0, 1.0, after_s=30.0))

    def test_degrade_tag_after(self) -> None:
        from run_results import DIR_RE, degrade_tag_to_spec

        name = "MH_04_difficult_baseline_stale_1_after_30_20260910_120000"
        m = DIR_RE.match(name)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("degrade_tag"), "stale_1_after_30")
        self.assertEqual(degrade_tag_to_spec("stale_1_after_30"), "stale:1:after=30")
        self.assertEqual(degrade_tag_to_spec("lag_0p5"), "lag:0.5")

    def test_imu_vis_window_split(self) -> None:
        from summarize_imu_vis import summarize_imu_vis

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "imu_vis.csv"
            with path.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["timestamp", "d", "dR_rad", "flow_med_px", "n_tracks", "skip"])
                w.writerow([100.5, 0.8, 0.1, 0.1, 10, 0])
                w.writerow([105.0, 0.1, 0.1, 1.0, 10, 0])
            d = summarize_imu_vis(path, bag_t0=100.0, stale_w=2.0)
            self.assertEqual(d["n"], 2)
            self.assertAlmostEqual(d["d_win_p50"] or 0, 0.8)
            self.assertAlmostEqual(d["d_live_p50"] or 0, 0.1)


class TestB2WilcoxonSmoke(unittest.TestCase):
    """Old B2 (non-reactive c(t)): bootstrap CI of mean ΔATE should contain 0."""

    B2 = ROOT / "datasets/results/batches/paper_main_20260825_101657"

    def test_b2_ci_contains_zero_on_mh04_d1(self) -> None:
        if not (self.B2 / "manifest.jsonl").is_file():
            self.skipTest("B2 batch not on disk")
        rows = load_batch_manifest(self.B2)
        cells = [c for c in aggregate_compare(rows) if c.seq == "MH_04_difficult" and c.degrade == "gaussian:5"]
        self.assertTrue(cells, "MH_04 D1 σ=5 missing from B2")
        ci = cells[0].bootstrap_mean_diff_ci()
        self.assertIsNotNone(ci)
        self.assertTrue(ci_contains_zero(ci), f"unexpected CI {ci}")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
