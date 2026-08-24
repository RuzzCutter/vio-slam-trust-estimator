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
    paired_ttest_p,
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
        self.assertGreaterEqual(PAIR_TTEST_MIN_N, 5)


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


if __name__ == "__main__":
    raise SystemExit(unittest.main())
