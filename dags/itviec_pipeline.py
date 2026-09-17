"""
ITviec Daily Pipeline DAG
=========================
Scrape → Process → Dashboard → Kaggle Push

Schedule: Daily at 07:00 ICT (UTC+7) = 00:00 UTC
Owner: quangnguyen
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = "/home/docutee/kaggle_pipeline"
DATA_DIR = "/mnt/kaggle_data/itviec"
LOG_DIR = "/mnt/kaggle_data/logs"
PYTHON = "/usr/bin/python3"
KAGGLE_BIN = "/home/docutee/.local/bin/kaggle"

DEFAULT_ARGS = {
    "owner": "quangnguyen",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=30),
}

# ─── DAG ──────────────────────────────────────────────────────────────────────
with DAG(
    dag_id="itviec_daily_pipeline",
    default_args=DEFAULT_ARGS,
    description="Daily ITviec job scraping, processing, dashboard & Kaggle push",
    schedule="0 0 * * *",  # 00:00 UTC = 07:00 ICT
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["itviec", "scraping", "kaggle", "daily"],
    doc_md="""
## ITviec Daily Pipeline

Automated daily pipeline that:
1. **Scrapes** all IT job listings from itviec.com
2. **Processes** data (clean, feature engineering, skill taxonomy)
3. **Builds** interactive Plotly dashboard
4. **Pushes** dataset to Kaggle

### Schedule
- Runs daily at **07:00 ICT** (00:00 UTC)

### Server
- `100.80.131.68` (Ubuntu 24.04, 8GB RAM)
- Data: `/mnt/kaggle_data/itviec/`
    """,
) as dag:

    start = EmptyOperator(task_id="start")

    # ─── STEP 1: SCRAPE ──────────────────────────────────────────────────
    scrape = BashOperator(
        task_id="scrape_itviec",
        bash_command=f"""
            cd {PROJECT_ROOT} && \
            {PYTHON} -m itviec \
                --output {DATA_DIR} \
                --workers 4 \
                --timeout 30 \
                --parquet \
                --verbose
        """,
        execution_timeout=timedelta(minutes=20),
    )

    # ─── STEP 2: PROCESS ─────────────────────────────────────────────────
    process = BashOperator(
        task_id="process_data",
        bash_command=f"""
            cd {DATA_DIR} && \
            cp {PROJECT_ROOT}/dashboard/process_data.py . && \
            {PYTHON} process_data.py {DATA_DIR}
        """,
    )

    # ─── STEP 3: DASHBOARD ───────────────────────────────────────────────
    build_dashboard = BashOperator(
        task_id="build_dashboard",
        bash_command=f"""
            cd {DATA_DIR} && \
            cp {PROJECT_ROOT}/dashboard/build_dashboard.py . && \
            {PYTHON} build_dashboard.py {DATA_DIR}
        """,
    )

    # ─── STEP 4: KAGGLE PUSH ─────────────────────────────────────────────
    def push_to_kaggle(**context):
        """Push dataset to Kaggle."""
        import json
        import subprocess

        kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
        if not kaggle_json.exists():
            logging.warning("kaggle.json not found, skipping push")
            return

        creds = json.loads(kaggle_json.read_text())
        env = os.environ.copy()
        env["KAGGLE_USERNAME"] = creds["username"]
        env["KAGGLE_API_TOKEN"] = creds["key"]

        kaggle_dir = Path(DATA_DIR) / "kaggle_upload"
        kaggle_dir.mkdir(parents=True, exist_ok=True)

        # Copy latest files
        import shutil
        for f in ["itviec_jobs_latest.csv", "itviec_jobs_latest.json", "processed_jobs.csv"]:
            src = Path(DATA_DIR) / f
            if src.exists():
                dst_name = f.replace("_latest", "")
                shutil.copy2(src, kaggle_dir / dst_name)

        # Write metadata
        meta = {
            "title": "ITviec Vietnam IT Job Listings",
            "id": "quangcrawler/itviec-jobs",
            "licenses": [{"name": "CC0-1.0"}],
        }
        (kaggle_dir / "dataset-metadata.json").write_text(json.dumps(meta, indent=2))

        # Push
        result = subprocess.run(
            [KAGGLE_BIN, "datasets", "create", "-p", str(kaggle_dir), "--dir-mode", "zip"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        if result.returncode != 0:
            # Try version update if create fails
            result = subprocess.run(
                [KAGGLE_BIN, "datasets", "version", "-m",
                 f"Daily update {context['ds']}", "-p", str(kaggle_dir), "--dir-mode", "zip"],
                capture_output=True, text=True, env=env, timeout=120,
            )

        logging.info("Kaggle push stdout: %s", result.stdout)
        if result.returncode != 0:
            logging.error("Kaggle push failed: %s", result.stderr)
            raise RuntimeError(f"Kaggle push failed: {result.stderr}")

        logging.info("Kaggle dataset updated successfully")

    kaggle_push = PythonOperator(
        task_id="kaggle_push",
        python_callable=push_to_kaggle,
        retries=1,
    )

    # ─── STEP 5: CLEANUP ─────────────────────────────────────────────────
    cleanup = BashOperator(
        task_id="cleanup_old_data",
        bash_command=f"""
            echo "Cleaning data older than 30 days..."
            find {DATA_DIR} -name "itviec_jobs_*.csv" -mtime +30 -delete 2>/dev/null || true
            find {DATA_DIR} -name "itviec_jobs_*.json" -mtime +30 -delete 2>/dev/null || true
            find {DATA_DIR} -name "itviec_jobs_*.parquet" -mtime +30 -delete 2>/dev/null || true
            find {LOG_DIR} -name "pipeline_*.log" -mtime +30 -delete 2>/dev/null || true
            echo "Cleanup done."
        """,
    )

    # ─── NOTIFY ──────────────────────────────────────────────────────────
    def notify_completion(**context):
        """Log completion summary."""
        ti = context["ti"]
        results = {
            "scrape": ti.xcom_pull(task_ids="scrape_itviec"),
            "process": ti.xcom_pull(task_ids="process_data"),
            "dashboard": ti.xcom_pull(task_ids="build_dashboard"),
            "kaggle": ti.xcom_pull(task_ids="kaggle_push"),
        }
        logging.info("=" * 60)
        logging.info("PIPELINE COMPLETE — %s", context["ds"])
        logging.info("Results: %s", results)
        logging.info("=" * 60)

    notify = PythonOperator(
        task_id="notify_completion",
        python_callable=notify_completion,
        trigger_rule=TriggerRule.ALL_SUCCESS,
    )

    end = EmptyOperator(task_id="end")

    # ─── DEPENDENCIES ────────────────────────────────────────────────────
    start >> scrape >> process >> build_dashboard >> kaggle_push >> cleanup >> notify >> end
