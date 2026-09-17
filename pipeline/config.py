"""Pipeline configuration."""
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "raw" / "topcv"
DASHBOARD_DATA = BASE_DIR / "data"

# Kaggle config
KAGGLE_USERNAME = os.getenv("KAGGLE_USERNAME", "docutee")
KAGGLE_DATASET_NAME = "topcv-it-jobs-vietnam"
KAGGLE_FULL_DATASET = f"{KAGGLE_USERNAME}/{KAGGLE_DATASET_NAME}"

# Scraper settings
SCRAPE_MAX_PAGES = 50
SCRAPE_HEADLESS = True

# Schedule
DAILY_CRON = "0 6 * * *"  # 6 AM daily
