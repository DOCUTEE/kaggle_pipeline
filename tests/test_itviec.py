"""Unit tests cho source ITviec: model + parser + snapshot (stdlib unittest).

Run:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json as json_mod
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup  # noqa: E402

from pipeline.sources.itviec.models import Job, JobLabel, WorkingType  # noqa: E402
from pipeline.sources.itviec.parser import (  # noqa: E402
    ParsingQualityError,
    parse_card,
    parse_page,
)

from pipeline.core.snapshot import SnapshotStore, split_list  # noqa: E402
from pipeline.sources.itviec.adapter import RAW_FIELDS, ItviecSource  # noqa: E402


CARD_HTML = """
<div class="job-card ipt-2 d-flex flex-column border-radius-large position-relative cursor-pointer transition-duration-300 bg-light-warning-color super-hot"
     data-action="click-&gt;search--job-selection#select"
     data-controller="search--job-selection"
     data-impressed="false"
     data-job-impressions-target="jobCard"
     data-job-key="72c7dc03-82bf-4078-bac0-e22d4e50fa37"
     data-search--job-selection-job-slug-value="senior-middle-site-reliability-engineer-5922"
     data-search--job-selection-job-url-value="/it-jobs/senior-middle-site-reliability-engineer-5922/content?job_index=0&amp;locale=en">
  <div class="ilabel position-absolute ilabel-danger end-0">SUPER HOT</div>
  <div class="ipy-2">
    <div class="d-flex align-items-center justify-content-between position-relative">
      <span class="small-text text-dark-grey">Posted 1 hour ago</span>
    </div>
    <h3 class="imt-3 text-break">
      <a class="text-it-black text-hover-red" href="/it-jobs/senior-middle-site-reliability-engineer-5922">Senior/Middle Site Reliability Engineer</a>
    </h3>
    <div class="text-rich-grey">NAB Innovation Centre Vietnam</div>
    <a class="sign-in-view-salary text-reset ips-2 text-decoration-underline stretched-link position-relative" href="#">Sign in to view salary</a>
    <div class="position-relative stretched-link text-rich-grey text-hover-red ips-2 text-truncate text-decoration-dot-underline small-text">Site Reliability Engineer (SRE)</div>
    <div class="text-rich-grey flex-shrink-0">Hybrid</div>
    <div class="text-rich-grey text-truncate text-nowrap stretched-link position-relative">Ho Chi Minh</div>
    <div class="text-reset text-nowrap stretched-link itag itag-light itag-sm position-relative">DevOps</div>
    <div class="text-reset text-nowrap stretched-link itag itag-light itag-sm position-relative">AWS</div>
    <div class="text-reset text-nowrap stretched-link itag itag-light itag-sm position-relative">English</div>
    <div class="imb-1">Very competitive remuneration package</div>
    <div class="imb-1">Hybrid and flexible working environment</div>
  </div>
</div>
"""

PAGE_HTML = f"""
<html><body>
  <div class="headline-total-jobs">765 IT jobs in Vietnam</div>
  <div class="card-jobs-list">
    {CARD_HTML}
    {CARD_HTML.replace("72c7dc03-82bf-4078-bac0-e22d4e50fa37", "aaaaaaaa-1111-2222-3333-444444444444")}
  </div>
</body></html>
"""


def _soup_card():
    return BeautifulSoup(CARD_HTML, "html.parser").find(class_="job-card")


class TestParseCard(unittest.TestCase):
    def test_full_parse(self):
        job = parse_card(_soup_card(), page=1, scraped_at="2026-09-14T00:00:00+00:00")
        self.assertEqual(job.job_key, "72c7dc03-82bf-4078-bac0-e22d4e50fa37")
        self.assertEqual(job.title, "Senior/Middle Site Reliability Engineer")
        self.assertEqual(job.url, "https://itviec.com/it-jobs/senior-middle-site-reliability-engineer-5922")
        self.assertEqual(job.company, "NAB Innovation Centre Vietnam")
        self.assertEqual(job.salary, "Sign in to view salary")
        self.assertEqual(job.working_type, WorkingType.HYBRID)
        self.assertEqual(job.location, "Ho Chi Minh")
        self.assertEqual(job.tags, ["DevOps", "AWS", "English"])
        self.assertEqual(job.posted_time, "1 hour ago")
        self.assertEqual(job.label, JobLabel.SUPER_HOT)
        self.assertEqual(job.highlights, [
            "Very competitive remuneration package",
            "Hybrid and flexible working environment",
        ])
        self.assertEqual(job.job_function, "Site Reliability Engineer (SRE)")
        self.assertEqual(job.page, 1)
        self.assertEqual(job.scraped_at, "2026-09-14T00:00:00+00:00")

    def test_at_office_and_hot(self):
        html = CARD_HTML.replace(">Hybrid</div>", ">At office</div>").replace("SUPER HOT", "HOT")
        job = parse_card(BeautifulSoup(html, "html.parser").find(class_="job-card"), page=1, scraped_at="")
        self.assertEqual(job.working_type, WorkingType.OFFICE)
        self.assertEqual(job.label, JobLabel.HOT)

    def test_relative_url_strips_tracking(self):
        html = CARD_HTML.replace(
            "/it-jobs/senior-middle-site-reliability-engineer-5922",
            "/it-jobs/abc-123?lab_feature=preview_jd_page&utm=x",
        )
        job = parse_card(BeautifulSoup(html, "html.parser").find(class_="job-card"), page=1, scraped_at="")
        self.assertEqual(job.url, "https://itviec.com/it-jobs/abc-123")

    def test_stable_dedup_key(self):
        job = parse_card(_soup_card(), page=1, scraped_at="")
        self.assertEqual(job.dedup_key, "72c7dc03-82bf-4078-bac0-e22d4e50fa37")

    def test_duplicate_tags_removed(self):
        html = CARD_HTML + "<div class='itag itag-light itag-sm'>AWS</div>"
        job = parse_card(BeautifulSoup(html, "html.parser").find(class_="job-card"), page=1, scraped_at="")
        self.assertEqual(job.tags.count("AWS"), 1)


class TestParsePage(unittest.TestCase):
    def test_parse_page_multiple_cards(self):
        jobs = parse_page(PAGE_HTML, page=1, scraped_at="")
        self.assertEqual(len(jobs), 2)

    def test_quality_threshold_fails_loud(self):
        broken = "<html><body><div class='job-card'><div>garbage</div></div></body></html>"
        with self.assertRaises(ParsingQualityError):
            parse_page(broken, page=1, scraped_at="")

    def test_empty_page_ok(self):
        self.assertEqual(parse_page("<html><body></body></html>", page=1, scraped_at=""), [])


class TestModels(unittest.TestCase):
    def test_working_type_enum(self):
        self.assertIs(WorkingType("At office"), WorkingType.OFFICE)
        self.assertIs(WorkingType("Hybrid"), WorkingType.HYBRID)

    def test_invalid_working_type_rejected(self):
        with self.assertRaises(ValueError):
            Job(title="x", working_type="On the moon")

    def test_extra_fields_forbidden(self):
        with self.assertRaises(ValueError):
            Job(title="x", unexpected_field=1)


class TestStorage(unittest.TestCase):
    """Raw snapshot giờ dùng SnapshotStore dùng chung (pipeline/core/snapshot.py)."""

    def _make_job(self, key: str, title: str = "Title") -> Job:
        return Job(
            job_key=key,
            title=title,
            company="Company",
            url=f"https://itviec.com/it-jobs/{key}",
            location="Ho Chi Minh",
            page=1,
            scraped_at="2026-09-14T00:00:00+00:00",
        )

    def _store(self, td: str) -> SnapshotStore:
        return SnapshotStore(Path(td), "itviec_jobs", key_field="job_id", source="itviec")

    def test_row_serialization(self):
        job = self._make_job("k1", "Data Engineer")
        job.tags = ["Python", "SQL"]
        job.working_type = WorkingType.OFFICE
        job.label = JobLabel.HOT
        row = ItviecSource._to_row(job)
        self.assertEqual(row["job_id"], "k1")
        self.assertEqual(row["skills"], ["Python", "SQL"])
        self.assertEqual(row["working_type"], "At office")
        self.assertEqual(row["label"], "HOT")
        self.assertLessEqual(set(RAW_FIELDS), set(row.keys()))

    def test_atomic_json_write(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            rows = [ItviecSource._to_row(self._make_job("k1")), ItviecSource._to_row(self._make_job("k2"))]
            result = store.save(rows, run_id="20260914_000000")
            self.assertEqual(result.total, 2)
            self.assertTrue(result.path_json.exists())
            self.assertTrue((Path(td) / "itviec_jobs_latest.json").exists())
            self.assertEqual(list(Path(td).glob("*.csv")), [])  # không còn CSV

    def test_json_preserves_list_types(self):
        with tempfile.TemporaryDirectory() as td:
            job = self._make_job("k1")
            job.tags = ["Python", "SQL"]
            job.highlights = ["Top company"]
            result = self._store(td).save([ItviecSource._to_row(job)], run_id="r1")
            payload = json_mod.loads(result.path_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["jobs"][0]["skills"], ["Python", "SQL"])
            self.assertEqual(payload["jobs"][0]["highlights"], ["Top company"])
            # split_list chỉ còn để đọc dữ liệu CSV legacy
            self.assertEqual(split_list("Python | SQL"), ["Python", "SQL"])

    def test_dedupe_in_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            rows = [
                ItviecSource._to_row(self._make_job("k1")),
                ItviecSource._to_row(self._make_job("k1", title="Updated")),
            ]
            result = store.save(rows, run_id="r1")
            self.assertEqual(result.total, 1)

    def test_json_payload_shape(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            result = store.save([ItviecSource._to_row(self._make_job("k1"))], run_id="r1")
            with open(result.path_json, encoding="utf-8") as f:
                payload = json_mod.load(f)
            self.assertEqual(payload["total_jobs"], 1)
            self.assertEqual(payload["source"], "itviec")
            self.assertEqual(payload["jobs"][0]["job_id"], "k1")
            self.assertEqual(payload["jobs"][0]["scraped_at"], "2026-09-14T00:00:00+00:00")

    def test_empty_snapshot_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertLogs("pipeline.core.snapshot", level="WARNING"):
                result = self._store(td).save([])
            self.assertEqual(result.total, 0)
            self.assertIsNone(result.path_json)
            self.assertEqual(sorted(Path(td).iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)