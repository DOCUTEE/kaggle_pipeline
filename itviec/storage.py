"""Storage layer: idempotent, atomic, CSV + JSON (and optional Parquet).

Design notes (senior-data-engineer review):
- **Atomic writes** (temp file + rename) so a crash mid-write never leaves a
  truncated CSV/JSON that later stages silently consume.
- **Deterministic run_id** lets repeated runs overwrite the same snapshot
  file (idempotent at the file level).
- CSV and JSON share the same transformation path.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from itviec.models import Job

logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "job_key",
    "title",
    "company",
    "salary",
    "job_function",
    "working_type",
    "location",
    "tags",
    "posted_time",
    "label",
    "highlights",
    "url",
    "page",
    "scraped_at",
    "source",
]

_CSV_LIST_SEP = " | "


def _to_csv_row(job: Job) -> dict:
    row = job.model_dump()
    row["tags"] = _CSV_LIST_SEP.join(job.tags)
    row["highlights"] = _CSV_LIST_SEP.join(job.highlights)
    row["working_type"] = job.working_type.value
    row["label"] = job.label.value
    return row


def _atomic_write(path: Path, writer: callable) -> None:
    """Write via temp file in the same dir, then atomic os.replace()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer(f)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _copy_latest(source: Path, latest_name: str) -> None:
    latest = source.parent / latest_name
    fd, tmp_name = tempfile.mkstemp(dir=str(source.parent), suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(source, tmp_name)
        os.replace(tmp_name, latest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


@dataclass
class StoreResult:
    """What a storage run did, for logging/metrics."""

    total: int = 0
    path_csv: Path | None = None
    path_json: Path | None = None
    path_parquet: Path | None = None


class JobStore:
    """File store with atomic writes; keyed snapshot per run."""

    def __init__(
        self,
        output_dir: Path,
        *,
        csv_enabled: bool = True,
        json_enabled: bool = True,
        parquet_enabled: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.csv_enabled = csv_enabled
        self.json_enabled = json_enabled
        self.parquet_enabled = parquet_enabled

    def save(
        self,
        jobs: Iterable[Job],
        *,
        run_id: str | None = None,
    ) -> StoreResult:
        """Write all jobs to snapshot files; returns written paths.

        Duplicate ``dedup_key`` within one batch is collapsed (last wins),
        keeping the snapshot idempotent.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        jobs = list(jobs)

        # Collapse duplicates by dedup key, last occurrence wins
        unique: dict[str, Job] = {}
        for job in jobs:
            unique[job.dedup_key] = job
        jobs = sorted(unique.values(), key=lambda j: (j.page, j.dedup_key))

        result = StoreResult(total=len(jobs))
        if self.csv_enabled:
            result.path_csv = self._write_csv(jobs, run_id)
        if self.json_enabled:
            result.path_json = self._write_json(jobs, run_id)
        if self.parquet_enabled:
            result.path_parquet = self._write_parquet(jobs, run_id)
        return result

    # ------------------------------------------------------------------
    def _write_csv(self, jobs: list[Job], run_id: str) -> Path:
        path = self.output_dir / f"itviec_jobs_{run_id}.csv"

        def writer(f):
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            w.writeheader()
            for job in jobs:
                w.writerow(_to_csv_row(job))

        _atomic_write(path, writer)
        _copy_latest(path, "itviec_jobs_latest.csv")
        return path

    def _write_json(self, jobs: list[Job], run_id: str) -> Path:
        path = self.output_dir / f"itviec_jobs_{run_id}.json"
        payload = {
            "scraped_at": run_id,
            "total_jobs": len(jobs),
            "jobs": [j.model_dump(mode="json") for j in jobs],
        }

        def writer(f):
            json.dump(payload, f, ensure_ascii=False, indent=2)

        _atomic_write(path, writer)
        _copy_latest(path, "itviec_jobs_latest.json")
        return path

    def _write_parquet(self, jobs: list[Job], run_id: str) -> Path:
        import pandas as pd

        path = self.output_dir / f"itviec_jobs_{run_id}.parquet"
        df = pd.DataFrame([_to_csv_row(j) for j in jobs])
        df.to_parquet(path, index=False)
        _copy_latest(path, "itviec_jobs_latest.parquet")
        return path