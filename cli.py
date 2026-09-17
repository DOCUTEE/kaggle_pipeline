#!/usr/bin/env python3
"""ITviec job scraper — CLI entry point.

Usage:
    python -m itviec            # or: python cli.py
    python -m itviec --max-pages 3 --workers 4
    python -m itviec --output data/itviec --no-json
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer

from itviec.client import AccessDeniedError, ItviecClient
from itviec.runner import ScrapeRunner
from itviec.storage import JobStore

app = typer.Typer(add_completion=False)

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=_LOG_FORMAT, stream=sys.stderr)


@app.command()
def scrape(
    output: Path = typer.Option(
        Path("data/itviec"), "--output", "-o", help="Output directory for CSV/JSON"
    ),
    workers: int = typer.Option(1, "--workers", "-w", min=1, max=16, help="Parallel page workers (1 = sequential)"),
    max_pages: int = typer.Option(None, "--max-pages", help="Cap pages scraped (for testing)"),
    min_delay: float = typer.Option(0.8, "--min-delay", help="Min politeness delay (s)"),
    max_delay: float = typer.Option(2.0, "--max-delay", help="Max politeness delay (s)"),
    timeout: int = typer.Option(30, "--timeout", help="HTTP timeout (s)"),
    no_csv: bool = typer.Option(False, "--no-csv", help="Skip CSV output"),
    no_json: bool = typer.Option(False, "--no-json", help="Skip JSON output"),
    parquet: bool = typer.Option(False, "--parquet", help="Also write Parquet"),
    fail_threshold: float = typer.Option(0.5, "--fail-threshold", help="Max allowed empty-required-field ratio"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging"),
) -> None:
    """Scrape all IT job listings from itviec.com into the output dir."""
    _setup_logging(verbose)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    client = ItviecClient(timeout=timeout, min_delay=min_delay, max_delay=max_delay)
    store = JobStore(
        output,
        csv_enabled=not no_csv,
        json_enabled=not no_json,
        parquet_enabled=parquet,
    )
    runner = ScrapeRunner(client, store, workers=workers, fail_threshold=fail_threshold)

    try:
        stats, result = runner.run(max_pages=max_pages)
    except AccessDeniedError as exc:
        logging.getLogger(__name__).error("Access denied: %s", exc)
        raise typer.Exit(code=2) from exc

    log = logging.getLogger("itviec")
    log.info("Scrape finished: %d pages fetched, %d failed, %d jobs stored",
             stats.pages_fetched, len(stats.pages_failed), result.total)
    if stats.pages_failed:
        log.warning("Failed pages: %s", stats.pages_failed)
        log.error("Data is INCOMPLETE: %d of %d pages failed (expected ~%d jobs)",
                  len(stats.pages_failed), stats.total_pages, stats.total_reported)
        raise typer.Exit(code=3)
    if result.path_csv:
        log.info("CSV   -> %s", result.path_csv)
    if result.path_json:
        log.info("JSON  -> %s", result.path_json)
    if result.path_parquet:
        log.info("PARQUET -> %s", result.path_parquet)


if __name__ == "__main__":
    app()