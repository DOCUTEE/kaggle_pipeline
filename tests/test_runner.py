"""Integration test cho runner — chốt lại "1 pattern cho mọi source".

Test đăng ký một source GIẢ (`stub`) hoàn toàn mới rồi chạy `run_one()`:
nếu runner còn chỗ nào hard-code itviec/topcv thì test này fail.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import runner, settings  # noqa: E402
from pipeline.core.contracts import PROCESSED_JSON, DbSpec, ProcessResult, ScrapeResult  # noqa: E402
from pipeline.core.dashboard import ChartSpec, Section, render_dashboard, standard_kpis  # noqa: E402
from pipeline.core.snapshot import SnapshotStore  # noqa: E402
from pipeline.core.transform import (  # noqa: E402
    build_processed_df,
    find_raw_json,
    load_processed_df,
    load_raw_jobs,
    write_processed_json,
)
from pipeline.sources import REGISTRY  # noqa: E402

try:
    from test_core import ROW_FULL
except ImportError:
    from tests.test_core import ROW_FULL


class StubSource:
    """Source tối giản, chỉ dùng core — không có code riêng cho pipeline."""

    name = "stub"

    def scrape(self, data_dir, *, max_pages=None, workers=1, timeout=30, verbose=False):
        data_dir = Path(data_dir)
        snapshot = SnapshotStore(data_dir, "stub_jobs", source=self.name).save(
            [dict(ROW_FULL, source=self.name, job_id="stub-1")]
        )
        return ScrapeResult(
            source=self.name, count=snapshot.total, raw_dir=data_dir,
            latest_json=data_dir / "stub_jobs_latest.json",
        )

    def process(self, data_dir, out_dir):
        rows = load_raw_jobs(find_raw_json(Path(data_dir), "stub_jobs"))
        df = build_processed_df(rows, source=self.name)
        json_path = write_processed_json(df, Path(out_dir), PROCESSED_JSON)
        return ProcessResult(source=self.name, rows=len(df), json_path=json_path)

    def dashboard(self, processed, out_dir):
        df = load_processed_df(processed.json_path)
        return render_dashboard(
            df=df, out_path=Path(out_dir) / "stub_dashboard.html",
            heading="Stub", page_title="Stub", kpis=standard_kpis(),
            sections=[Section("📍 Geo", (ChartSpec("bar_v", "Jobs", "location_clean"),))],
            data_url="https://example.com", data_label="example", source_label="Stub",
        )

    def load_db(self, processed) -> int:
        return 0

    def db_spec(self) -> DbSpec:
        return DbSpec(table="stub_jobs", columns={"title": "title"}, conflict_key="title")

    def staging_files(self, data_dir, dashboard_dir):
        return {Path(dashboard_dir) / PROCESSED_JSON: PROCESSED_JSON}


class TestRunnerPattern(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saved_settings = settings.SOURCES.get("stub")
        self._saved_registry = REGISTRY.get("stub")
        self._saved_data_root = settings.DATA_ROOT
        settings.DATA_ROOT = self.tmp / "data"  # không ghi vào data/ của repo
        settings.SOURCES["stub"] = settings.SourceSettings(
            name="stub",
            raw_subdir="stub",
            kaggle_dataset="user/stub-jobs",
            schedule="0 0 * * *",
            default_max_pages=1,
            default_workers=1,
            raw_prefix="stub_jobs",
        )
        REGISTRY["stub"] = StubSource()

    def tearDown(self):
        if self._saved_settings is None:
            settings.SOURCES.pop("stub", None)
        else:
            settings.SOURCES["stub"] = self._saved_settings
        if self._saved_registry is None:
            REGISTRY.pop("stub", None)
        else:
            REGISTRY["stub"] = self._saved_registry
        settings.DATA_ROOT = self._saved_data_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_source_runs_all_six_steps_without_touching_runner(self):
        opts = runner.RunOptions(
            data_dir=self.tmp / "raw",
            dashboard_dir=self.tmp / "dash",
            push_kaggle=False,
            load_db=False,
        )
        summary = runner.run_one("stub", opts)

        self.assertIsNone(summary.error)
        self.assertEqual(summary.steps_ok, ["scrape", "process", "dashboard", "cleanup"])
        self.assertEqual(summary.steps_skipped, ["load_db", "kaggle_push"])
        self.assertEqual(summary.jobs, 1)
        self.assertEqual(summary.rows, 1)

        self.assertTrue((self.tmp / "raw" / "stub_jobs_latest.json").exists())
        self.assertTrue((self.tmp / "dash" / PROCESSED_JSON).exists())
        self.assertTrue((self.tmp / "dash" / "stub_dashboard.html").exists())

    def test_multi_source_rejects_shared_dir_override(self):
        """2 source dùng chung schema processed_jobs.csv → override dir sẽ ghi đè nhau."""
        with self.assertRaises(ValueError):
            runner.run_many(
                ["stub", "itviec"],
                runner.RunOptions(data_dir=self.tmp / "shared", push_kaggle=False),
            )

    def test_run_many_records_failure_without_stopping_others(self):
        class BrokenSource(StubSource):
            name = "broken"

            def process(self, data_dir, out_dir):
                raise RuntimeError("boom")

        REGISTRY["broken"] = BrokenSource()
        settings.SOURCES["broken"] = settings.SourceSettings(
            name="broken", raw_subdir="broken", kaggle_dataset="user/broken",
            schedule="0 0 * * *", default_max_pages=1, raw_prefix="broken_jobs",
        )
        try:
            with self.assertLogs("pipeline.runner", level="ERROR"):
                results = runner.run_many(
                    ["broken", "stub"],
                    runner.RunOptions(push_kaggle=False),
                )
        finally:
            REGISTRY.pop("broken", None)
            settings.SOURCES.pop("broken", None)

        self.assertEqual(len(results), 2)
        self.assertIn("boom", results[0].error or "")
        self.assertIsNone(results[1].error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
