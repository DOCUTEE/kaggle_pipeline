"""Unified runner — 1 PATTERN duy nhất cho mọi source.

Mỗi source chạy đúng 6 bước giống nhau, và runner **không có nhánh nào theo
tên source**: mọi khác biệt nằm trong package `pipeline/sources/<ten>/`.

    1. scrape      (adapter.scrape)
    2. process     (adapter.process)      — schema chuẩn ở core/transform
    3. dashboard   (adapter.dashboard)    — shell chung ở core/dashboard
    4. load_db     (adapter.load_db)      — optional, loader chung ở pipeline/db.py
    5. kaggle_push (adapter.staging_files) — staging + push ở core/publish
    6. cleanup     (xoá snapshot > keep_days)

Mọi entrypoint đều gọi vào đây:
    - Airflow: dags/jobs_daily.py (scheduler duy nhất)
    - Manual:  python -m pipeline run itviec|topcv|all, scripts/run_pipeline.sh
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pipeline import settings
from pipeline.core import publish
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
    steps_failed: list[str] = field(default_factory=list)
    jobs: int = 0          # jobs scrape được
    rows: int = 0          # rows sau process
    duration_s: float = 0.0
    error: str | None = None


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def run_one(source_name: str, opts: RunOptions | None = None) -> StepSummary:
    """Chạy full 6 bước cho 1 source."""
    opts = opts or RunOptions()
    summary = StepSummary(source=source_name)
    t0 = time.time()

    cfg = settings.get_source(source_name)
    src = get_source(source_name)

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
    scrape = src.scrape(
        data_dir, max_pages=max_pages, workers=workers,
        timeout=opts.timeout, verbose=opts.verbose,
    )
    summary.jobs = scrape.count
    summary.steps_ok.append("scrape")
    logger.info("[%s] scrape done: %d jobs", source_name, scrape.count)

    if scrape.count == 0:
        logger.warning("[%s] 0 jobs — vẫn chạy tiếp process/dashboard trên snapshot cũ.", source_name)

    # 2. PROCESS ─────────────────────────────────────────────────────────
    processed = src.process(data_dir, dashboard_dir)
    summary.rows = processed.rows
    summary.steps_ok.append("process")

    # 3. DASHBOARD ───────────────────────────────────────────────────────
    src.dashboard(processed, dashboard_dir)
    summary.steps_ok.append("dashboard")

    # 4. LOAD DB (optional) ──────────────────────────────────────────────
    if opts.load_db:
        src.load_db(processed)
        summary.steps_ok.append("load_db")
    else:
        summary.steps_skipped.append("load_db")

    # 5. KAGGLE PUSH (optional) ──────────────────────────────────────────
    if opts.push_kaggle:
        staging = publish.prepare_staging(
            settings.kaggle_dir_for(data_dir), src.staging_files(data_dir, dashboard_dir)
        )
        if publish.push_to_kaggle(staging, kaggle_id):
            summary.steps_ok.append("kaggle_push")
        else:
            # Dữ liệu đã vào Postgres rồi — không coi cả run là fail, nhưng phải
            # hiện ra rõ (trước đây luôn báo ok nên lỗi này bị che).
            summary.steps_failed.append("kaggle_push")
            logger.warning("[%s] kaggle_push THẤT BẠI — xem log phía trên", source_name)
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
    opts = opts or RunOptions()
    if len(sources) > 1 and (opts.data_dir or opts.dashboard_dir):
        # Mọi source dùng chung 1 schema processed_jobs.json → override thư mục cho
        # nhiều source sẽ khiến chúng ghi đè nhau. DAG truyền --data-dir riêng cho
        # từng task nên vẫn đúng.
        raise ValueError(
            "--data-dir/--dashboard-dir chỉ dùng được với 1 source "
            f"(đang chạy {len(sources)}: {', '.join(sources)}). "
            "Bỏ override để mỗi source dùng thư mục riêng trong DATA_ROOT."
        )

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

def _cleanup_old_snapshots(data_dir: Path, keep_days: int = 30) -> None:
    """Xóa snapshot timestamped cũ hơn keep_days. Không đụng *_latest.*."""
    if keep_days <= 0:
        return
    cutoff = time.time() - keep_days * 86400
    # giữ pattern .csv để dọn luôn snapshot CSV cũ trên server
    patterns = ("*_20*.json", "*_20*.csv", "*_20*.parquet")
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
        if r.error:
            status = f"ERROR: {r.error}"
        else:
            status = f"jobs={r.jobs} rows={r.rows} steps={r.steps_ok}"
            if r.steps_failed:
                status += f" ⚠ FAILED={r.steps_failed}"
        print(f"#  - {r.source}: {status}")
    print(f"{'#' * 60}")
