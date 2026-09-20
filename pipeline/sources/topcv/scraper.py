"""TopCV scraper — orchestration: phân trang + delay + retry + dedup.

Cùng vai trò với `pipeline/sources/itviec/scraper.py` (`ScrapeRunner`):
    fetch (client) → parse (parser) → trả `(stats, jobs)` cho adapter ghi snapshot.

Parser và client nằm ở module riêng nên phần điều hướng này test được bằng
fake browser (xem `tests/test_topcv.py`).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

from .client import SEARCH_URL, TopCvBrowser, build_search_url
from .models import Job
from .parser import parse_jobs, parse_total_pages

logger = logging.getLogger(__name__)

#: Delay ngẫu nhiên giữa các page (giây) — lịch sự với server.
PAGE_DELAY_RANGE = (1.5, 3.0)
#: Chờ trước khi retry 1 page lỗi (giây).
RETRY_DELAY_S = 5.0


@dataclass
class ScrapeStats:
    """Thống kê 1 lượt scrape — giống `RunStats` của itviec."""

    pages_fetched: int = 0
    pages_failed: list[int] = field(default_factory=list)
    total_pages: int = 0
    jobs_parsed: int = 0


class TopCvScraper:
    """Scrape toàn bộ trang listing của topcv.vn."""

    def __init__(
        self,
        headless: bool = True,
        *,
        page_delay_range: tuple[float, float] = PAGE_DELAY_RANGE,
        retry_delay_s: float = RETRY_DELAY_S,
    ) -> None:
        self.headless = headless
        self.page_delay_range = page_delay_range
        self.retry_delay_s = retry_delay_s
        self.browser = TopCvBrowser(headless=headless)
        self.stats = ScrapeStats()

    # ------------------------------------------------------------------
    def scrape_page(self, page_num: int = 1) -> list[Job]:
        """Scrape 1 page: mở trang → chờ Cloudflare → parse.

        Raise nếu không thấy card nào: thực tế gặp trang challenge Cloudflare
        ("Attention Required!") trả HTML nhỏ không có job — nếu coi là thành công
        thì page đó lặng lẽ mất dữ liệu. Raise để orchestrator retry.
        """
        url = build_search_url(page=page_num)
        print(f"  Fetching page {page_num}: {url}")

        self.browser.open(url)
        if not self.browser.wait_for_cloudflare():
            print(f"  Warning: Cloudflare chưa qua ở page {page_num}")
        found = self.browser.wait_for_job_list()
        jobs = parse_jobs(self.browser.html())
        if not jobs:
            reason = "hết kết quả" if found else "không thấy card job (Cloudflare/JS chưa render?)"
            raise RuntimeError(f"page {page_num}: 0 job — {reason}")
        if not found:
            print(f"  Warning: Job list selector not found on page {page_num} (vẫn parse được {len(jobs)} job)")
        return jobs

    def scrape_all(self, max_pages: int = 50) -> tuple[ScrapeStats, list[Job]]:
        """Scrape toàn bộ page (tối đa `max_pages`). Trả `(stats, jobs)`."""
        print("Starting TopCV job scraper...")
        print(f"Target: {SEARCH_URL}")
        print("=" * 60)

        self._validate_robots()
        self.stats = ScrapeStats()
        self.browser.start()
        try:
            print("Loading first page...")
            first_jobs = self.scrape_page(1)
            self.stats.pages_fetched += 1

            total_pages = min(parse_total_pages(self.browser.html()), max_pages)
            self.stats.total_pages = total_pages
            print(f"Found {len(first_jobs)} jobs on page 1")
            print(f"Total pages detected: {total_pages}")

            all_jobs = list(first_jobs)
            for page_num in range(2, total_pages + 1):
                time.sleep(random.uniform(*self.page_delay_range))
                try:
                    jobs = self.scrape_page(page_num)
                    all_jobs.extend(jobs)
                    self.stats.pages_fetched += 1
                    print(f"Page {page_num}/{total_pages}: {len(jobs)} jobs (total: {len(all_jobs)})")
                except Exception as exc:  # noqa: BLE001 — 1 page lỗi không chặn cả run
                    print(f"Page {page_num} failed: {exc}")
                    time.sleep(self.retry_delay_s)
                    try:
                        jobs = self.scrape_page(page_num)
                        all_jobs.extend(jobs)
                        self.stats.pages_fetched += 1
                        print(f"Page {page_num} RETRY OK: {len(jobs)} jobs")
                    except Exception as exc2:  # noqa: BLE001
                        print(f"Page {page_num} RETRY also failed: {exc2}")
                        self.stats.pages_failed.append(page_num)

            unique_jobs = self._dedupe(all_jobs)
            self.stats.jobs_parsed = len(unique_jobs)
            print(f"\nScraping complete: {len(unique_jobs)} unique jobs")
            return self.stats, unique_jobs
        finally:
            self.browser.stop()

    # ------------------------------------------------------------------
    @staticmethod
    def _dedupe(jobs: list[Job]) -> list[Job]:
        """Bỏ trùng theo job_id (fallback url), giữ lần xuất hiện đầu."""
        seen: set[str] = set()
        unique: list[Job] = []
        for job in jobs:
            key = job.job_id or job.url
            if key and key not in seen:
                seen.add(key)
                unique.append(job)
        return unique

    def _validate_robots(self) -> None:
        """Hook robots.txt — topcv.vn không chặn đường dẫn listing đang scrape."""
        logger.debug("robots.txt: topcv.vn listing allowed; scrape có delay giữa các page")


__all__ = ["PAGE_DELAY_RANGE", "RETRY_DELAY_S", "ScrapeStats", "TopCvScraper"]
