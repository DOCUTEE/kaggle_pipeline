"""Unit tests cho core dùng chung (transform / db spec / dashboard / snapshot).

Chạy: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from pipeline import db as dbmod  # noqa: E402
from pipeline.core.contracts import PROCESSED_JSON, DbSpec  # noqa: E402
from pipeline.core.dashboard import (  # noqa: E402
    ChartSpec,
    KpiSpec,
    Section,
    build_chart,
    render_dashboard,
    standard_kpis,
)
from pipeline.core.snapshot import (  # noqa: E402
    SnapshotStore,
    atomic_write_text,
    split_list,
)
from pipeline.core.transform import (  # noqa: E402
    PROCESSED_CORE_FIELDS,
    build_processed_df,
    extract_seniority,
    load_processed_df,
    normalize_location,
    parse_posted_hours,
    write_processed_json,
)

ROW_FULL = {
    "job_id": "k1",
    "title": "Senior Data Engineer",
    "company": "ACME",
    "url": "https://example.com/1",
    "salary": "2000 USD",
    "location": "Hồ Chí Minh",
    "skills": ["Python", "SQL", "Airflow"],
    "posted_date": "3 hours ago",
    "scraped_at": "2026-09-20T00:00:00+00:00",
    "source": "itviec",
    # cột riêng của từng source (union)
    "job_function": "Data Engineer",
    "working_type": "Remote",
    "label": "HOT",
    "highlights": ["Top company"],
    "page": 1,
    "company_url": "https://example.com/co",
    "experience": "3 năm kinh nghiệm",
    "level": "Senior",
    "job_type": "Full-time",
    "category": "CNTT",
    "deadline": "2026-10-01",
    "is_hot": True,
    "is_urgent": False,
    "scrape_date": "2026-09-20",
}


class TestTransform(unittest.TestCase):
    def test_extract_seniority_english(self):
        self.assertEqual(extract_seniority("Senior Backend Engineer"), "Senior/Lead")
        self.assertEqual(extract_seniority("Marketing Intern"), "Intern")
        self.assertEqual(extract_seniority("Engineering Manager"), "Manager+")
        self.assertEqual(extract_seniority("Backend Developer", "3 years experience"), "Mid-level")
        self.assertEqual(extract_seniority("Backend Developer"), "Not specified")

    def test_extract_seniority_vietnamese(self):
        self.assertEqual(extract_seniority("Thực tập sinh IT"), "Intern")
        self.assertEqual(extract_seniority("Kỹ sư phần mềm", "5 năm kinh nghiệm"), "Senior/Lead")
        self.assertEqual(extract_seniority("Nhân viên IT", "Giám đốc"), "Manager+")

    def test_parse_posted_hours(self):
        self.assertEqual(parse_posted_hours("3 hours ago"), 3.0)
        self.assertEqual(parse_posted_hours("45 minutes ago"), 0.75)
        self.assertEqual(parse_posted_hours("2 ngày trước"), 48.0)
        self.assertEqual(parse_posted_hours("1 tuần trước"), 168.0)
        self.assertIsNone(parse_posted_hours(""))
        self.assertIsNone(parse_posted_hours("hôm qua"))

    def test_normalize_location(self):
        self.assertEqual(normalize_location("Hồ Chí Minh"), "Ho Chi Minh")
        self.assertEqual(normalize_location("Ha Noi"), "Ha Noi")
        self.assertEqual(normalize_location("Hà Nội"), "Ha Noi")
        self.assertEqual(normalize_location("Đà Nẵng"), "Da Nang")
        self.assertEqual(normalize_location("Ho Chi Minh, Ha Noi"), "HCM + Ha Noi")
        self.assertEqual(normalize_location(""), "Unknown")

    def test_build_processed_df_schema_and_features(self):
        df = build_processed_df([ROW_FULL, {**ROW_FULL, "job_id": "k2", "title": ""}], source="itviec")

        # row thiếu title bị loại
        self.assertEqual(len(df), 1)
        # cột core luôn có mặt và đứng trước
        self.assertEqual(list(df.columns)[: len(PROCESSED_CORE_FIELDS)], list(PROCESSED_CORE_FIELDS))
        # cột riêng của source vẫn được giữ
        for extra in ("working_type", "is_hot", "experience"):
            self.assertIn(extra, df.columns)

        row = df.iloc[0]
        self.assertEqual(row["location_clean"], "Ho Chi Minh")
        self.assertEqual(row["num_skills"], 3)
        self.assertEqual(row["seniority"], "Senior/Lead")
        self.assertEqual(row["posted_hours_ago"], 3.0)
        self.assertIn("Data & AI", row["skill_categories"])

    def test_build_processed_df_cleans_salary_placeholder(self):
        rows = [{**ROW_FULL, "salary": "Sign in to view salary"}, {**ROW_FULL, "job_id": "k2", "salary": None}]
        df = build_processed_df(rows, source="itviec")
        self.assertEqual(list(df["salary"]), ["", ""])

    def test_build_processed_df_empty(self):
        df = build_processed_df([], source="topcv")
        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), list(PROCESSED_CORE_FIELDS))

    def test_processed_json_roundtrip_keeps_types(self):
        df = build_processed_df([ROW_FULL], source="itviec")
        with tempfile.TemporaryDirectory() as td:
            path = write_processed_json(df, Path(td), PROCESSED_JSON)
            self.assertTrue(path.exists())
            back = load_processed_df(path)
            self.assertEqual(list(Path(td).iterdir()), [path])  # chỉ JSON, không CSV
        self.assertEqual(back.iloc[0]["skills"], ["Python", "SQL", "Airflow"])
        self.assertEqual(back.iloc[0]["skill_categories"], ["Data & AI", "Database", "Languages"])
        self.assertEqual(back.iloc[0]["job_id"], "k1")
        self.assertTrue(bool(back.iloc[0]["has_highlights"]))
        self.assertEqual(back.iloc[0]["num_skills"], 3)


class TestSnapshotCore(unittest.TestCase):
    def test_split_list_handles_nan_and_empty(self):
        self.assertEqual(split_list("a | b"), ["a", "b"])
        self.assertEqual(split_list(""), [])
        self.assertEqual(split_list(float("nan")), [])
        self.assertEqual(split_list(["x"]), ["x"])

    def test_shared_file_mode(self):
        """File trên volume dùng chung (host uid 1000 + container uid 50000) phải đọc được."""
        with tempfile.TemporaryDirectory() as td:
            result = SnapshotStore(Path(td), "x_jobs", key_field="job_id", source="x").save(
                [{"job_id": "1", "title": "t"}]
            )
            self.assertEqual(stat.S_IMODE(result.path_json.stat().st_mode), 0o664)
            self.assertEqual(
                stat.S_IMODE((Path(td) / "x_jobs_latest.json").stat().st_mode), 0o664
            )
            html = atomic_write_text(Path(td) / "dash.html", "<html/>")
            self.assertEqual(stat.S_IMODE(html.stat().st_mode), 0o664)

    def test_atomic_overwrite_of_foreign_file(self):
        """File do user khác tạo (không ghi được) vẫn phải overwrite được qua rename."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            store = SnapshotStore(d, "x_jobs", key_field="job_id", source="x")
            store.save([{"job_id": "1", "title": "v1"}], run_id="r1")
            latest = d / "x_jobs_latest.json"
            latest.chmod(0o444)  # chỉ đọc → write_text() sẽ fail, atomic replace thì không

            store.save([{"job_id": "1", "title": "v2"}], run_id="r2")
            self.assertIn("v2", latest.read_text(encoding="utf-8"))

            html = atomic_write_text(d / "dash.html", "<html>v1</html>")
            html.chmod(0o444)
            atomic_write_text(d / "dash.html", "<html>v2</html>")
            self.assertEqual(html.read_text(encoding="utf-8"), "<html>v2</html>")

    def test_latest_alias_points_to_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            store = SnapshotStore(Path(td), "topcv_jobs", key_field="job_id", source="topcv")
            result = store.save([{**ROW_FULL, "skills": ["Python"], "source": "topcv"}],
                                run_id="20260920_010101")
            latest = Path(td) / "topcv_jobs_latest.json"
            self.assertTrue(latest.exists())
            self.assertTrue((Path(td) / "topcv_jobs_20260920_010101.json").exists())
            # chỉ có JSON: không sinh file CSV nào
            self.assertEqual(sorted(p.suffix for p in Path(td).iterdir()), [".json", ".json"])
            self.assertEqual(result.path_json.name, "topcv_jobs_20260920_010101.json")


class TestDbSpec(unittest.TestCase):
    SPEC = DbSpec(
        table="demo",
        columns={"job_id": "job_id", "title": "title", "tags": "skills", "is_hot": "is_hot"},
        conflict_key="job_id",
        update_columns=("title",),
        json_columns=("tags",),
        bool_columns=("is_hot",),
        text_columns=("job_id",),
    )

    def test_coerce_row_types(self):
        row = pd.Series({"job_id": 123, "title": None, "skills": "Python | SQL", "is_hot": "False"})
        values = dbmod.coerce_row(row, self.SPEC)
        self.assertEqual(values, ('123', None, '["Python", "SQL"]', False))

    def test_coerce_row_bool_variants(self):
        for raw, expected in (("True", True), ("true", True), (True, True), (float("nan"), False), ("0", False)):
            row = pd.Series({"job_id": "1", "title": "t", "skills": [], "is_hot": raw})
            self.assertIs(dbmod.coerce_row(row, self.SPEC)[3], expected)

    def test_build_insert_sql(self):
        sql = dbmod.build_insert_sql(self.SPEC)
        self.assertIn("INSERT INTO demo (job_id, title, tags, is_hot)", sql)
        self.assertIn("ON CONFLICT (job_id) DO UPDATE SET", sql)
        self.assertIn("loaded_at = NOW()", sql)


class TestDashboard(unittest.TestCase):
    def _df(self) -> pd.DataFrame:
        return build_processed_df([ROW_FULL, {**ROW_FULL, "job_id": "k2", "title": "Junior Tester"}], source="itviec")

    def test_build_chart_skips_missing_column(self):
        self.assertIsNone(build_chart(self._df(), ChartSpec("bar_v", "X", "khong_ton_tai")))

    def test_render_dashboard_writes_html_and_skips_unknown_charts(self):
        sections = [
            Section("📍 Geo", (
                ChartSpec("bar_v", "Jobs by Location", "location_clean"),
                ChartSpec("bar_v", "Không có cột này", "khong_ton_tai"),
            )),
            Section("🛠️ Skills", (
                ChartSpec("bar_h", "Top skills", "skills", list_column=True, full=True),
            )),
        ]
        with tempfile.TemporaryDirectory() as td:
            out = render_dashboard(
                df=self._df(), out_path=Path(td) / "dash.html",
                heading="Test", page_title="Test", sections=sections,
                kpis=standard_kpis(KpiSpec("🔥", "Hot", "share", column="label_clean", values=("HOT",))),
                data_url="https://example.com", data_label="example", source_label="Test",
            )
            html = out.read_text(encoding="utf-8")
        self.assertIn("plotly", html.lower())
        self.assertIn("chart-card", html)
        self.assertIn("Key Insights", html)
        self.assertNotIn("Không có cột này", html)

    def test_kpi_share_on_list_column(self):
        df = self._df()
        spec = KpiSpec("🐍", "Python jobs", "share", column="skills", values=("Python",), list_column=True)
        from pipeline.core.dashboard import _kpi_cards

        self.assertIn("100.0%", _kpi_cards(df, [spec]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
