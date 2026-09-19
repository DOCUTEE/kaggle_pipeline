"""Contract test — mọi source phải theo ĐÚNG 1 pattern.

Test này là "chốt" của refactor: thêm source mới mà quên implement 1 bước,
hoặc quên đăng ký ở settings, hoặc để lọt `if source == ...` vào runner,
đều fail ngay ở CI.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import settings  # noqa: E402
from pipeline.core.contracts import PROCESSED_JSON, DbSpec  # noqa: E402
from pipeline.core.transform import build_processed_df  # noqa: E402
from pipeline.sources import ALL_SOURCES, REGISTRY, get_source  # noqa: E402

try:  # chạy qua `unittest discover -s tests` chỉ thêm tests/ vào sys.path
    from test_core import ROW_FULL  # type: ignore[import-not-found]
except ImportError:
    from tests.test_core import ROW_FULL

REQUIRED_METHODS = ("scrape", "process", "dashboard", "load_db", "db_spec", "staging_files")
SCRAPE_PARAMS = {"data_dir", "max_pages", "workers", "timeout", "verbose"}
REPO_ROOT = Path(__file__).resolve().parents[1]


class TestSourceContract(unittest.TestCase):
    def test_expected_sources_are_registered(self):
        self.assertEqual(ALL_SOURCES, sorted(ALL_SOURCES))
        self.assertEqual(set(ALL_SOURCES), {"itviec", "topcv"})

    def test_registry_matches_settings(self):
        self.assertEqual(set(REGISTRY), set(settings.SOURCES))

    def test_every_source_implements_all_steps(self):
        for name in ALL_SOURCES:
            src = get_source(name)
            self.assertEqual(src.name, name)
            for method in REQUIRED_METHODS:
                self.assertTrue(callable(getattr(src, method, None)), f"{name} thiếu {method}()")

    def test_uniform_signatures(self):
        for name in ALL_SOURCES:
            src = get_source(name)
            self.assertLessEqual(
                SCRAPE_PARAMS, set(inspect.signature(src.scrape).parameters),
                f"{name}.scrape() sai chữ ký",
            )
            self.assertLessEqual({"data_dir", "out_dir"}, set(inspect.signature(src.process).parameters))
            self.assertLessEqual({"processed", "out_dir"}, set(inspect.signature(src.dashboard).parameters))
            self.assertLessEqual({"data_dir", "dashboard_dir"}, set(inspect.signature(src.staging_files).parameters))

    def test_db_spec_is_valid_and_matches_processed_schema(self):
        df = build_processed_df([ROW_FULL], source="itviec")

        for name in ALL_SOURCES:
            spec = get_source(name).db_spec()
            self.assertIsInstance(spec, DbSpec)
            self.assertIn(spec.conflict_key, spec.columns, f"{name}: conflict_key không nằm trong columns")
            for col in spec.update_columns:
                self.assertIn(col, spec.columns, f"{name}: update column {col} không có trong columns")
            for group in (spec.json_columns, spec.bool_columns, spec.text_columns):
                for col in group:
                    self.assertIn(col, spec.columns, f"{name}: cột {col} không có trong columns")

            missing = [csv_col for csv_col in spec.columns.values() if csv_col not in df.columns]
            self.assertEqual(missing, [], f"{name}: DbSpec trỏ vào cột không có trong processed schema: {missing}")

    def test_staging_files_contract(self):
        data_dir = REPO_ROOT / "data" / "itviec"
        dashboard_dir = data_dir / "dashboard"

        for name in ALL_SOURCES:
            mapping = get_source(name).staging_files(data_dir, dashboard_dir)
            self.assertIsInstance(mapping, dict)
            self.assertTrue(mapping, f"{name}: staging_files() rỗng")
            for src_path, dest_name in mapping.items():
                self.assertIsInstance(src_path, Path)
                self.assertTrue(dest_name.endswith(".json"), f"{name}: chỉ publish JSON, gặp {dest_name}")
            self.assertIn(PROCESSED_JSON, mapping.values(), f"{name}: thiếu processed JSON khi publish")

    def test_settings_complete(self):
        for name in ALL_SOURCES:
            cfg = settings.get_source(name)
            self.assertTrue(cfg.raw_prefix, f"{name}: thiếu raw_prefix")
            self.assertTrue(cfg.processed_json.endswith(".json"))
            self.assertTrue(cfg.kaggle_dataset.count("/") == 1, f"{name}: kaggle_dataset phải là 'user/dataset'")

    def test_runner_has_no_source_branching(self):
        """Runner phải source-agnostic — không được rẽ nhánh theo tên source."""
        runner_src = (REPO_ROOT / "pipeline" / "runner.py").read_text(encoding="utf-8")
        for needle in ('== "itviec"', '== "topcv"', "source_name ==", "if source =="):
            self.assertNotIn(needle, runner_src, f"runner.py còn rẽ nhánh theo source: {needle}")

    def test_adapters_do_not_import_each_other(self):
        for name in ALL_SOURCES:
            other = "topcv" if name == "itviec" else "itviec"
            src = (REPO_ROOT / "pipeline" / "sources" / f"{name}.py").read_text(encoding="utf-8")
            self.assertNotIn(f"sources.{other}", src, f"{name}.py import adapter của {other}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
