"""Unified pipeline settings — single source of truth.

Thay thế config rải rác ở pipeline/config.py (TopCV only).

Scheduler là CRON: scripts/cron_daily.sh (07:00 ICT), cài qua deploy/setup_server.sh.
Trường `schedule` dưới đây chỉ để document — crontab mới là source of truth.

Mọi entrypoint (CLI, cron) đều đọc từ đây + env vars,
nên local và server chỉ khác env, không khác code.

Env hỗ trợ:
    PROJECT_ROOT   — root repo (default: tự phát hiện từ file này)
    DATA_ROOT      — thư mục data (default: <PROJECT_ROOT>/data)
    KAGGLE_USERNAME / KAGGLE_API_TOKEN — creds push Kaggle (token KGAT_...
    lấy ở kaggle.com/settings/api; cần kaggle>=2.0)
    ITVIEC_KAGGLE_DATASET / TOPCV_KAGGLE_DATASET
    DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _project_root() -> Path:
    # pipeline/settings.py -> parent.parent = repo root
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT: Path = Path(os.getenv("PROJECT_ROOT", str(_project_root())))
DATA_ROOT: Path = Path(os.getenv("DATA_ROOT", str(PROJECT_ROOT / "data")))
LOG_DIR: Path = Path(os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs")))

KAGGLE_USERNAME: str = os.getenv("KAGGLE_USERNAME", "docutee")


@dataclass(frozen=True)
class SourceSettings:
    """Cấu hình cố định cho 1 nguồn dữ liệu."""

    name: str                       # "itviec" | "topcv"
    raw_subdir: str                 # thư mục raw dưới DATA_ROOT, vd "itviec"
    kaggle_dataset: str             # id đầy đủ "user/dataset"
    schedule: str                   # document lịch chạy (crontab là source of truth)
    default_max_pages: int | None   # None = toàn bộ
    default_workers: int = 4
    raw_prefix: str = ""            # tiền tố file raw: <prefix>_latest.json
    dashboard_html: str = "dashboard.html"
    processed_json: str = "processed_jobs.json"


SOURCES: dict[str, SourceSettings] = {
    "itviec": SourceSettings(
        name="itviec",
        raw_subdir="itviec",
        kaggle_dataset=os.getenv("ITVIEC_KAGGLE_DATASET", "quangcrawler/itviec-jobs"),
        schedule="0 7 * * *",           # document: cron 07:00 ICT (scripts/cron_daily.sh)
        default_max_pages=None,     # scrape toàn bộ
        default_workers=4,
        raw_prefix="itviec_jobs",
        dashboard_html="itviec_dashboard.html",
    ),
    "topcv": SourceSettings(
        name="topcv",
        raw_subdir=os.getenv("TOPCV_RAW_SUBDIR", "raw/topcv"),
        kaggle_dataset=os.getenv(
            "TOPCV_KAGGLE_DATASET", f"{KAGGLE_USERNAME}/topcv-it-jobs-vietnam"
        ),
        schedule="0 7 * * *",           # document: cron 07:00 ICT (scripts/cron_daily.sh)
        # Phân trang chạy được nhờ backend CloakBrowser (xem
        # pipeline/sources/topcv/client.py) — Playwright thường bị Cloudflare trả
        # "Attention Required!" từ page 2. Cap 60 page (~3.000 job) để tránh chạy
        # vô hạn nếu site báo sai số trang.
        default_max_pages=60,
        default_workers=1,          # Playwright chạy tuần tự
        raw_prefix="topcv_jobs",
        dashboard_html="topcv_dashboard.html",
    ),
}


def get_source(name: str) -> SourceSettings:
    try:
        return SOURCES[name]
    except KeyError:
        raise ValueError(
            f"Unknown source {name!r}. Choose from: {sorted(SOURCES)}"
        ) from None


def data_dir_for(name: str, override: Path | None = None) -> Path:
    """Thư mục raw của 1 source. Override dùng cho server (/mnt/kaggle_data/...)."""
    if override:
        return Path(override)
    return DATA_ROOT / get_source(name).raw_subdir


def dashboard_dir_for(data_dir: Path, override: Path | None = None) -> Path:
    if override:
        return Path(override)
    return Path(data_dir) / "dashboard"


def kaggle_dir_for(data_dir: Path) -> Path:
    """Staging dir chuẩn để push Kaggle (tránh push cả thư mục raw)."""
    return Path(data_dir) / "kaggle_upload"


# ─── DB (giữ nguyên contract cũ của pipeline/db.py) ───────────────────────────

DB_CONFIG: dict = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "kaggle_pipeline"),
    "user": os.getenv("DB_USER", "pipeline"),
    "password": os.getenv("DB_PASSWORD", "pipeline_dev_2024"),
}
