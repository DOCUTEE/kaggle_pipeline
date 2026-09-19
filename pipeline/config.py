"""Pipeline configuration — COMPAT SHIM.

Canonical config đã chuyển sang pipeline/settings.py (multi-source).
File này giữ lại để pipeline/daily_pipeline.py cũ vẫn import được.
Code mới hãy dùng:
    from pipeline import settings
    settings.data_dir_for("topcv")
"""
import os
from pathlib import Path

from pipeline.settings import (  # noqa: F401 — re-export cho code cũ
    DATA_ROOT,
    KAGGLE_USERNAME,
    PROJECT_ROOT,
    SOURCES,
    data_dir_for,
)

# Paths
BASE_DIR = PROJECT_ROOT
DATA_DIR = data_dir_for("topcv")
DASHBOARD_DATA = DATA_ROOT

# Kaggle config
KAGGLE_DATASET_NAME = "topcv-it-jobs-vietnam"
KAGGLE_FULL_DATASET = f"{KAGGLE_USERNAME}/{KAGGLE_DATASET_NAME}"

# Scraper settings
SCRAPE_MAX_PAGES = 50
SCRAPE_HEADLESS = True

# Schedule
DAILY_CRON = "0 6 * * *"  # 6 AM daily
