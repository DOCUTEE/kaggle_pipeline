#!/usr/bin/env python3
"""
Daily Pipeline: Scrape TopCV → Clean → Push to Kaggle
"""

import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.topcv_scraper import TopCVScraper, save_results, Job
from pipeline.config import (
    DATA_DIR, KAGGLE_USERNAME, KAGGLE_DATASET_NAME,
    KAGGLE_FULL_DATASET, SCRAPE_MAX_PAGES
)


def scrape_jobs() -> list[Job]:
    """Run the scraper."""
    print(f"\n{'='*60}")
    print(f"SCRAPING: {datetime.now().isoformat()}")
    print(f"{'='*60}")

    scraper = TopCVScraper(headless=True)
    jobs = scraper.scrape_all(max_pages=SCRAPE_MAX_PAGES)
    print(f"Total scraped: {len(jobs)} jobs")
    return jobs


def clean_data(jobs: list[Job]) -> list[Job]:
    """Clean and normalize scraped data."""
    print(f"\nCleaning {len(jobs)} jobs...")

    cleaned = []
    for job in jobs:
        # Normalize salary
        if job.salary:
            job.salary = job.salary.strip()
            if job.salary.lower() in ("", "none", "null"):
                job.salary = "Thỏa thuận"

        # Normalize location
        if not job.location:
            job.location = "Hà Nội"  # Default

        # Clean title
        job.title = job.title.strip()

        if job.title:
            cleaned.append(job)

    print(f"Cleaned: {len(cleaned)} jobs")
    return cleaned


def merge_with_existing(new_jobs: list[Job]) -> list[Job]:
    """Merge new jobs with existing data (if any)."""
    today = datetime.now().strftime("%Y-%m-%d")
    latest_file = DATA_DIR / "topcv_jobs_latest.json"

    existing_ids = set()
    if latest_file.exists():
        with open(latest_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            for job in data.get("jobs", []):
                if job.get("job_id"):
                    existing_ids.add(job["job_id"])

    # Only add truly new jobs
    unique_new = [j for j in new_jobs if j.job_id not in existing_ids]
    print(f"Existing jobs: {len(existing_ids)}, New unique: {len(unique_new)}")

    return new_jobs  # Return all for daily snapshot


def push_to_kaggle(data_dir: Path):
    """Push dataset to Kaggle."""
    print(f"\nPushing to Kaggle: {KAGGLE_FULL_DATASET}")

    # Create/update dataset metadata
    metadata = {
        "title": "TopCV IT Jobs Vietnam - Daily Dataset",
        "id": f"{KAGGLE_USERNAME}/{KAGGLE_DATASET_NAME}",
        "licenses": [{"name": "CC0-1.0"}],
    }

    metadata_path = data_dir / "dataset-metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Prepare kaggle.json credentials
    kaggle_dir = Path.home() / ".kaggle"
    kaggle_dir.mkdir(exist_ok=True)
    kaggle_json = kaggle_dir / "kaggle.json"

    kaggle_key = os.getenv("KAGGLE_KEY", "")
    if kaggle_key and not kaggle_json.exists():
        with open(kaggle_json, "w") as f:
            json.dump({"username": KAGGLE_USERNAME, "key": kaggle_key}, f)
        kaggle_json.chmod(0o600)

    # Copy latest files to data_dir for upload
    import shutil
    latest_csv = DATA_DIR / "topcv_jobs_latest.csv"
    latest_json = DATA_DIR / "topcv_jobs_latest.json"

    if latest_csv.exists():
        shutil.copy2(latest_csv, data_dir / "topcv_jobs.csv")
    if latest_json.exists():
        shutil.copy2(latest_json, data_dir / "topcv_jobs.json")

    # Push using kaggle CLI
    try:
        result = subprocess.run(
            ["kaggle", "datasets", "version", "-m",
             f"Daily update {datetime.now().strftime('%Y-%m-%d %H:%M')}",
             "-p", str(data_dir),
             "--dir-mode", "zip"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            print("Kaggle push SUCCESS!")
            print(result.stdout)
        else:
            print(f"Kaggle push failed: {result.stderr}")
            # Try creating dataset first
            result2 = subprocess.run(
                ["kaggle", "datasets", "create", "-p", str(data_dir),
                 "--dir-mode", "zip"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result2.returncode == 0:
                print("Kaggle dataset created successfully!")
                print(result2.stdout)
            else:
                print(f"Kaggle create also failed: {result2.stderr}")
    except FileNotFoundError:
        print("Kaggle CLI not found. Install with: pip install kaggle")
    except subprocess.TimeoutExpired:
        print("Kaggle push timed out")


def run_pipeline():
    """Execute the full daily pipeline."""
    start_time = datetime.now()
    print(f"\n{'#'*60}")
    print(f"# DAILY PIPELINE START: {start_time.isoformat()}")
    print(f"{'#'*60}")

    try:
        # Step 1: Scrape
        jobs = scrape_jobs()

        if not jobs:
            print("No jobs scraped. Aborting.")
            return

        # Step 2: Clean
        cleaned = clean_data(jobs)

        # Step 3: Merge/Save locally
        merged = merge_with_existing(cleaned)
        json_path, csv_path = save_results(merged)

        # Step 4: Push to Kaggle
        push_to_kaggle(DATA_DIR)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"\n{'#'*60}")
        print(f"# PIPELINE COMPLETE: {end_time.isoformat()}")
        print(f"# Duration: {duration:.1f}s")
        print(f"# Jobs: {len(merged)}")
        print(f"{'#'*60}")

    except Exception as e:
        print(f"\nPIPELINE ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    run_pipeline()
