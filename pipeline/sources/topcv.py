"""TopCV source adapter — bọc scraper/TopCVScraper theo BaseSource."""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.sources.base import ScrapeResult

logger = logging.getLogger(__name__)


class TopcvSource:
    name = "topcv"

    def scrape(
        self,
        data_dir: Path,
        *,
        max_pages: int | None = 50,
        workers: int = 1,  # Playwright chạy tuần tự, giữ param cho đồng nhất interface
        timeout: int = 30,
        verbose: bool = False,
    ) -> ScrapeResult:
        from scraper.topcv_scraper import TopCVScraper, save_results

        _ = (workers, timeout, verbose)  # chưa dùng, giữ để interface đồng nhất
        data_dir = Path(data_dir)
        scraper = TopCVScraper(headless=True)
        jobs = scraper.scrape_all(max_pages=max_pages or 50)

        if not jobs:
            logger.warning("TopCV scraped 0 jobs")
            return ScrapeResult(source=self.name, count=0, raw_dir=data_dir)

        # save_results() tự ghi file timestamped + latest copies
        json_path, csv_path = save_results(jobs, output_dir=data_dir)
        return ScrapeResult(
            source=self.name,
            count=len(jobs),
            raw_dir=data_dir,
            latest_csv=Path(csv_path),
            latest_json=Path(json_path),
        )
