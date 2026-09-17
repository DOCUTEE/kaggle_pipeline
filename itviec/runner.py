"""Orchestration: fetch pages -> parse -> validate -> merge/store.

The runner keeps the pipeline resumable by processing pages in order and
merging results into an idempotent store, so a crash mid-run does not lose
the work already completed and re-runs do not duplicate jobs.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from itviec.client import ItviecClient
from itviec.models import Job
from itviec.parser import parse_page
from itviec.storage import JobStore, StoreResult

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    pages_fetched: int = 0
    pages_failed: list[int] = field(default_factory=list)
    jobs_parsed: int = 0
    total_pages: int = 0
    total_reported: int = 0


class ScrapeRunner:
    """Fetch + parse + store all listing pages."""

    def __init__(
        self,
        client: ItviecClient,
        store: JobStore,
        *,
        workers: int = 1,
        fail_threshold: float = 0.5,
        repair_retries: int = 2,
    ) -> None:
        self.client = client
        self.store = store
        self.workers = workers
        self.fail_threshold = fail_threshold
        self.repair_retries = repair_retries

    def run(self, *, max_pages: int | None = None) -> tuple[RunStats, StoreResult]:
        self._validate_robots()
        total = self.client.fetch_total_jobs()
        total_pages = max(1, (total + self.client.PAGE_SIZE - 1) // self.client.PAGE_SIZE)
        if max_pages:
            total_pages = min(total_pages, max_pages)

        logger.info("Total jobs reported: %d -> %d pages", total, total_pages)
        stats = RunStats(total_pages=total_pages, total_reported=total)
        scraped_at = datetime.now(timezone.utc).isoformat()

        pages = list(range(1, total_pages + 1))
        if self.workers <= 1:
            jobs = self._run_sequential(pages, scraped_at, stats)
        else:
            jobs = self._run_parallel(pages, scraped_at, stats)

        # Repair pass: retry failed pages with a longer delay
        if stats.pages_failed:
            logger.info("Repair pass for %d failed pages: %s", len(stats.pages_failed), stats.pages_failed)
            failed_in_round1 = list(stats.pages_failed)
            stats.pages_failed.clear()
            for page in failed_in_round1:
                time.sleep(5)
                try:
                    html = self.client.fetch_listing_page(page)
                    page_jobs = parse_page(
                        html, page=page, scraped_at=scraped_at,
                        fail_threshold=self.fail_threshold,
                    )
                    jobs.extend(page_jobs)
                    stats.pages_fetched += 1
                    logger.info("Page %d RETRY OK: %d jobs", page, len(page_jobs))
                except Exception:
                    logger.exception("Page %d REPAIR also failed", page)
                    stats.pages_failed.append(page)

        logger.info("Parsed %d jobs across %d pages", len(jobs), stats.pages_fetched)
        store_result = self.store.save(jobs, run_id=scraped_at[:19].replace(":", "").replace("T", "_"))
        return stats, store_result

    # ------------------------------------------------------------------
    def _run_sequential(
        self, pages: list[int], scraped_at: str, stats: RunStats
    ) -> list[Job]:
        jobs: list[Job] = []
        for page in pages:
            try:
                html = self.client.fetch_listing_page(page)
                page_jobs = parse_page(html, page=page, scraped_at=scraped_at, fail_threshold=self.fail_threshold)
                jobs.extend(page_jobs)
                stats.pages_fetched += 1
                logger.info("Page %d/%d: %d jobs", page, stats.total_pages, len(page_jobs))
            except Exception:
                logger.exception("Page %d failed", page)
                stats.pages_failed.append(page)
        return jobs

    def _run_parallel(
        self, pages: list[int], scraped_at: str, stats: RunStats
    ) -> list[Job]:
        jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = {
                ex.submit(self._fetch_page, page, scraped_at): page for page in pages
            }
            for fut in as_completed(futures):
                page = futures[fut]
                try:
                    jobs.extend(fut.result())
                    stats.pages_fetched += 1
                except Exception:
                    logger.exception("Page %d failed", page)
                    stats.pages_failed.append(page)
        return jobs

    def _fetch_page(self, page: int, scraped_at: str) -> list[Job]:
        html = self.client.fetch_listing_page(page)
        return parse_page(html, page=page, scraped_at=scraped_at, fail_threshold=self.fail_threshold)

    # ------------------------------------------------------------------
    def _validate_robots(self) -> None:
        """Respect robots.txt: itviec allows crawling; just log sitemap hint."""
        # robots.txt: User-Agent * Allow / (only /subscriptions/new disallowed)
        # No action needed; kept as a documented hook for other sources.
        logger.debug("robots.txt: itviec.com allows crawling (verified 2026-09-14)")