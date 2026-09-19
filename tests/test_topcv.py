"""Unit tests cho source TopCV — parser chạy offline + orchestration với browser giả.

Nhờ tách client/parser/scraper, phần parse HTML và phần phân trang/retry/dedup
test được mà KHÔNG cần Playwright browser (CI không có Chromium).
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.sources.topcv.client import build_search_url  # noqa: E402
from pipeline.sources.topcv.models import Job  # noqa: E402
from pipeline.sources.topcv.parser import (  # noqa: E402
    parse_job_card,
    parse_jobs,
    parse_total_pages,
)
from pipeline.sources.topcv.scraper import TopCvScraper  # noqa: E402


def card(job_id: str, title: str, company: str = "ACME") -> str:
    return f"""
    <div class="job-item" data-job-id="{job_id}">
      <h3><a href="/it-jobs/{job_id}.html">{title}</a></h3>
      <a class="company" href="/companies/acme">{company}</a>
      <span class="salary">2000 USD</span>
      <span class="location">Hà Nội</span>
      <span class="experience">3 năm kinh nghiệm</span>
      <span class="level">Senior</span>
      <span class="tag">Python</span><span class="tag">SQL</span>
      <span class="time">2 ngày trước</span>
      <span class="badge">HOT</span>
    </div>"""


PAGINATION = '<ul class="pagination"><a class="page">1</a><a class="page">2</a><a class="page">3</a></ul>'


class FakeBrowser:
    """Browser giả: trả HTML theo page, không cần Playwright."""

    def __init__(self, pages: dict[int, str]) -> None:
        self.pages = pages
        self.opened: list[str] = []
        self.current = ""
        self.started = False

    def start(self): self.started = True
    def stop(self): self.started = False
    def open(self, url, **_): 
        self.opened.append(url)
        page = int(url.split("page=")[-1]) if "page=" in url else 1
        self.current = self.pages.get(page, "")
    def wait_for_cloudflare(self, timeout_s: int = 15): return True
    def wait_for_job_list(self, **_): return True
    def html(self): return self.current


class TestTopcvParser(unittest.TestCase):
    def test_parse_job_card_fields(self):
        job = parse_job_card(card("123456", "Senior Data Engineer"))
        self.assertIsNotNone(job)
        self.assertEqual(job.job_id, "123456")
        self.assertEqual(job.title, "Senior Data Engineer")
        self.assertEqual(job.company, "ACME")
        self.assertEqual(job.url, "https://www.topcv.vn/it-jobs/123456.html")
        self.assertEqual(job.company_url, "https://www.topcv.vn/companies/acme")
        self.assertEqual(job.salary, "2000 USD")
        self.assertEqual(job.location, "Hà Nội")
        self.assertEqual(job.level, "Senior")
        self.assertEqual(job.skills, ["Python", "SQL"])
        self.assertTrue(job.is_hot)
        self.assertFalse(job.is_urgent)
        self.assertTrue(job.scrape_date)  # __post_init__ set ngày hôm nay

    def test_parse_job_card_without_title_returns_none(self):
        self.assertIsNone(parse_job_card('<div class="job-item" data-job-id="1"></div>'))

    def test_parse_job_card_falls_back_to_url_id(self):
        html = '<div class="job-item"><h3><a href="/it-jobs/backend-dev-98765.html">Backend Dev</a></h3></div>'
        job = parse_job_card(html)
        self.assertEqual(job.job_id, "98765")

    def test_parse_jobs_from_listing(self):
        html = f"<html><body>{card('1', 'A')}{card('2', 'B')}</body></html>"
        jobs = parse_jobs(html)
        self.assertEqual([j.title for j in jobs], ["A", "B"])

    def test_parse_total_pages(self):
        self.assertEqual(parse_total_pages(f"<html>{PAGINATION}</html>"), 3)
        self.assertEqual(parse_total_pages("<html><body>no pagination</body></html>"), 1)
        self.assertEqual(
            parse_total_pages('<html><a rel="next" href="/tim-viec-lam?page=7">next</a></html>'), 7
        )

    def test_build_search_url(self):
        self.assertNotIn("page=", build_search_url(page=1))
        self.assertIn("page=3", build_search_url(page=3))
        self.assertIn("q=python", build_search_url(page=1, keyword="python"))


class TestTopcvScraper(unittest.TestCase):
    def _scraper(self, pages: dict[int, str]) -> TopCvScraper:
        scraper = TopCvScraper(headless=True, page_delay_range=(0, 0), retry_delay_s=0)
        scraper.browser = FakeBrowser(pages)  # inject browser giả
        return scraper

    def test_scrape_all_paginates_and_dedupes(self):
        pages = {
            1: f"<html><body>{card('1', 'A')}{card('2', 'B')}{PAGINATION}</body></html>",
            2: f"<html><body>{card('2', 'B trùng')}{card('3', 'C')}</body></html>",
        }
        scraper = self._scraper(pages)
        with contextlib.redirect_stdout(io.StringIO()):
            stats, jobs = scraper.scrape_all(max_pages=2)

        self.assertEqual(stats.total_pages, 2)     # pagination báo 3 nhưng bị cap bởi max_pages
        self.assertEqual(stats.pages_fetched, 2)
        self.assertEqual(stats.pages_failed, [])
        self.assertEqual(stats.jobs_parsed, 3)     # A, B, C (B ở page 2 bị dedup)
        self.assertEqual([j.title for j in jobs], ["A", "B", "C"])
        self.assertFalse(scraper.browser.started)  # browser luôn được stop()

    def test_scrape_all_retries_failed_page_once(self):
        class FlakyBrowser(FakeBrowser):
            """Lần đầu mở page 2 thì lỗi, lần retry thì OK."""

            def __init__(self, pages):
                super().__init__(pages)
                self.page2_tries = 0

            def open(self, url, **kwargs):
                if "page=2" in url:
                    self.page2_tries += 1
                    if self.page2_tries == 1:
                        raise RuntimeError("boom")
                super().open(url, **kwargs)

        pages = {1: f"<html>{card('1', 'A')}{PAGINATION}</html>", 2: f"<html>{card('2', 'B')}</html>"}
        scraper = self._scraper(pages)
        scraper.browser = FlakyBrowser(pages)
        with contextlib.redirect_stdout(io.StringIO()):
            stats, jobs = scraper.scrape_all(max_pages=2)

        self.assertEqual(stats.pages_failed, [])
        self.assertEqual([j.title for j in jobs], ["A", "B"])

    def test_scrape_all_stops_browser_on_error(self):
        class BrokenBrowser(FakeBrowser):
            def open(self, url, **_):
                raise RuntimeError("browser chết")

        scraper = self._scraper({})
        scraper.browser = BrokenBrowser({})
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                scraper.scrape_all(max_pages=1)
        self.assertFalse(scraper.browser.started)

    def test_dedupe_keeps_first_occurrence(self):
        jobs = [Job(job_id="1", title="first"), Job(job_id="1", title="second"), Job(url="u", title="x")]
        self.assertEqual([j.title for j in TopCvScraper._dedupe(jobs)], ["first", "x"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
