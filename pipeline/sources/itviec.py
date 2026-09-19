"""ITviec source adapter — bọc itviec/Client+Runner+Store theo BaseSource."""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.sources.base import ScrapeResult

logger = logging.getLogger(__name__)


class ItviecSource:
    name = "itviec"

    def scrape(
        self,
        data_dir: Path,
        *,
        max_pages: int | None = None,
        workers: int = 4,
        timeout: int = 30,
        verbose: bool = False,
    ) -> ScrapeResult:
        from itviec.client import AccessDeniedError, ItviecClient
        from itviec.runner import ScrapeRunner
        from itviec.storage import JobStore

        data_dir = Path(data_dir)
        client = ItviecClient(timeout=timeout)
        store = JobStore(data_dir, parquet_enabled=False)
        runner = ScrapeRunner(client, store, workers=workers)

        try:
            stats, result = runner.run(max_pages=max_pages)
        except AccessDeniedError:
            logger.exception("ITviec access denied")
            raise

        if stats.pages_failed:
            logger.warning(
                "ITviec incomplete: %d/%d pages failed: %s",
                len(stats.pages_failed),
                stats.total_pages,
                stats.pages_failed,
            )

        latest_csv = data_dir / "itviec_jobs_latest.csv"
        latest_json = data_dir / "itviec_jobs_latest.json"
        return ScrapeResult(
            source=self.name,
            count=result.total,
            raw_dir=data_dir,
            latest_csv=latest_csv if latest_csv.exists() else result.path_csv,
            latest_json=latest_json if latest_json.exists() else result.path_json,
            extra={
                "pages_fetched": stats.pages_fetched,
                "pages_failed": list(stats.pages_failed),
            },
        )
