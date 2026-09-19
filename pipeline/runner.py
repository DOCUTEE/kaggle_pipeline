"""Unified runner — 1 PATTERN duy nhất cho mọi source.

Mỗi source chạy đúng 6 bước giống nhau:
    1. scrape      (adapter trong pipeline/sources/)
    2. process     (pipeline/build.py)
    3. dashboard   (pipeline/build.py)
    4. load_db     (pipeline/db.py, optional)
    5. kaggle_push (pipeline/build.py, optional, qua staging dir chuẩn)
    6. cleanup     (xóa snapshot > 30 ngày)

Mọi entrypoint đều gọi vào đây:
    - Airflow: dags/jobs_daily.py (scheduler duy nhất)
    - Manual:  python -m pipeline run itviec|topcv|all, scripts/run_pipeline.sh
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pipeline import settings
from pipeline.sources import ALL_SOURCES, get_source

logger = logging.getLogger(__name__)


@dataclass
class RunOptions:
    data_dir: Path | None = None       # override raw dir (vd /mnt/kaggle_data/itviec)
    dashboard_dir: Path | None = None  # override dashboard dir
    max_pages: int | None = None       # None = dùng default của source
    workers: int | None = None         # None = dùng default của source
    timeout: int = 30
    load_db: bool = False
    push_kaggle: bool = True
    kaggle_dataset: str | None = None  # override id "user/dataset"
    keep_days: int = 30                # cleanup snapshot cũ hơn N ngày
    verbose: bool = False


@dataclass
class StepSummary:
    source: str
    steps_ok: list[str] = field(default_factory=list)
    steps_skipped: list[str] = field(default_factory=list)
    jobs: int = 0
    duration_s: float = 0.0
    error: str | None = None


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def run_one(source_name: str, opts: RunOptions | None = None) -> StepSummary:
    """Chạy full 6 bước cho 1 source."""
    opts = opts or RunOptions()
    summary = StepSummary(source=source_name)
    t0 = time.time()

    cfg = settings.get_source(source_name)
    adapter = get_source(source_name)

    data_dir = settings.data_dir_for(cfg.name, opts.data_dir)
    dashboard_dir = settings.dashboard_dir_for(data_dir, opts.dashboard_dir)
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    max_pages = cfg.default_max_pages if opts.max_pages is None else opts.max_pages
    workers = cfg.default_workers if opts.workers is None else opts.workers
    kaggle_id = opts.kaggle_dataset or cfg.kaggle_dataset

    logger.info(
        "[%s] start: data=%s dashboard=%s max_pages=%s workers=%s",
        source_name, data_dir, dashboard_dir, max_pages, workers,
    )

    # 1. SCRAPE ──────────────────────────────────────────────────────────
    scrape = adapter.scrape(
        data_dir, max_pages=max_pages, workers=workers,
        timeout=opts.timeout, verbose=opts.verbose,
    )
    summary.jobs = scrape.count
    summary.steps_ok.append("scrape")
    logger.info("[%s] scrape done: %d jobs", source_name, scrape.count)

    if scrape.count == 0:
        logger.warning("[%s] 0 jobs — vẫn chạy tiếp process/dashboard trên latest.", source_name)

    # 2. PROCESS ─────────────────────────────────────────────────────────
    from pipeline import build as build_mod

    if source_name == "itviec":
        build_mod.process_itviec(data_dir, dashboard_dir)
    else:
        build_mod.process_topcv(data_dir, dashboard_dir)
    summary.steps_ok.append("process")

    # 3. DASHBOARD ───────────────────────────────────────────────────────
    if source_name == "itviec":
        build_mod.build_itviec_dashboard(data_dir, dashboard_dir)
    else:
        build_mod.build_topcv_dashboard(data_dir, dashboard_dir)
    summary.steps_ok.append("dashboard")

    # 4. LOAD DB (optional) ──────────────────────────────────────────────
    if opts.load_db:
        from pipeline import db as db_mod

        csv_name = "processed_jobs.csv" if source_name == "itviec" else "processed_topcv.csv"
        csv_path = dashboard_dir / csv_name
        if not csv_path.exists():
            raise FileNotFoundError(f"Processed CSV not found: {csv_path}")
        if source_name == "itviec":
            db_mod.load_itviec_csv(csv_path)
        else:
            db_mod.load_topcv_csv(csv_path)
        summary.steps_ok.append("load_db")
    else:
        summary.steps_skipped.append("load_db")

    # 5. KAGGLE PUSH (optional) ──────────────────────────────────────────
    if opts.push_kaggle:
        staging = _prepare_kaggle_staging(source_name, data_dir, dashboard_dir)
        build_mod.push_to_kaggle(staging, kaggle_id)
        summary.steps_ok.append("kaggle_push")
    else:
        summary.steps_skipped.append("kaggle_push")

    # 6. CLEANUP ─────────────────────────────────────────────────────────
    _cleanup_old_snapshots(data_dir, keep_days=opts.keep_days)
    summary.steps_ok.append("cleanup")

    summary.duration_s = time.time() - t0
    logger.info(
        "[%s] done in %.1fs: %s (skipped: %s)",
        source_name, summary.duration_s, summary.steps_ok, summary.steps_skipped,
    )
    return summary


def run_many(sources: list[str], opts: RunOptions | None = None) -> list[StepSummary]:
    """Chạy tuần tự nhiều source. Source lỗi không chặn source sau (ghi error)."""
    results: list[StepSummary] = []
    for name in sources:
        try:
            results.append(run_one(name, opts))
        except Exception as exc:  # noqa: BLE001 — pipeline phải chạy hết các source
            logger.exception("[%s] pipeline failed", name)
            results.append(StepSummary(source=name, error=str(exc)))
    return results


def run_all(opts: RunOptions | None = None) -> list[StepSummary]:
    return run_many(ALL_SOURCES, opts)


# ─── INTERNALS ────────────────────────────────────────────────────────────────

def _prepare_kaggle_staging(source: str, data_dir: Path, dashboard_dir: Path) -> Path:
    """Chuẩn hóa staging dir cho Kaggle: latest raw + processed + metadata."""
    staging = settings.kaggle_dir_for(data_dir)
    staging.mkdir(parents=True, exist_ok=True)

    if source == "itviec":
        wanted = {
            data_dir / "itviec_jobs_latest.csv": "itviec_jobs.csv",
            data_dir / "itviec_jobs_latest.json": "itviec_jobs.json",
            dashboard_dir / "processed_jobs.csv": "processed_jobs.csv",
        }
    else:
        wanted = {
            data_dir / "topcv_jobs_latest.csv": "topcv_jobs.csv",
            data_dir / "topcv_jobs_latest.json": "topcv_jobs.json",
            dashboard_dir / "processed_topcv.csv": "processed_topcv.csv",
        }

    for src, dst_name in wanted.items():
        if src.exists():
            shutil.copy2(src, staging / dst_name)
        else:
            logger.warning("Kaggle staging: missing %s (skip)", src)

    return staging


def _cleanup_old_snapshots(data_dir: Path, keep_days: int = 30) -> None:
    """Xóa snapshot timestamped cũ hơn keep_days. Không đụng *_latest.*."""
    if keep_days <= 0:
        return
    cutoff = time.time() - keep_days * 86400
    patterns = ("*_20*.csv", "*_20*.json", "*_20*.parquet")
    for pat in patterns:
        for p in data_dir.glob(pat):
            if "latest" in p.name:
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    logger.info("cleanup: removed %s", p.name)
            except OSError:
                logger.warning("cleanup: cannot remove %s", p, exc_info=True)


def print_summary(results: list[StepSummary]) -> None:
    print(f"\n{'#' * 60}")
    print(f"# PIPELINE COMPLETE: {datetime.now().isoformat()}")
    for r in results:
        status = f"ERROR: {r.error}" if r.error else f"jobs={r.jobs} steps={r.steps_ok}"
        print(f"#  - {r.source}: {status}")
    print(f"{'#' * 60}")
