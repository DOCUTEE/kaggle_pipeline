"""
Jobs daily DAG — scheduler DUY NHẤT của pipeline (không dùng cron).

PATTERN: DAG chỉ orchestrate, logic nằm ở pipeline/runner.py.
Mỗi source = 1 BashOperator gọi `python -m pipeline run <source>`.
Thêm source mới: thêm tên vào PIPELINE_SOURCES (không sửa cấu trúc DAG).

Schedule: daily 00:00 UTC = 07:00 ICT.
Triển khai: `cd infra && docker compose up -d airflow-scheduler airflow-webserver`
UI: http://localhost:8080 (xem infra/docker-compose.yml).

Local không cài Airflow vẫn `python -m pipeline run ...` bình thường:
file này import-safe (thiếu airflow -> DAG = None).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

try:
    from airflow import DAG
    from airflow.operators.bash import BashOperator
    from airflow.operators.empty import EmptyOperator
    from airflow.operators.python import PythonOperator

    _AIRFLOW_AVAILABLE = True
except ImportError:  # local dev không cần airflow
    _AIRFLOW_AVAILABLE = False
    DAG = BashOperator = EmptyOperator = PythonOperator = None  # type: ignore

# ─── CONFIG (env-overridable, không hardcode user/server) ────────────────────
PROJECT_ROOT = os.getenv("PROJECT_ROOT", "/home/docutee/kaggle_pipeline")
PYTHON = os.getenv("PIPELINE_PYTHON", "/usr/bin/python3")
DATA_ROOT = os.getenv("DATA_ROOT", "/mnt/kaggle_data")
# Postgres luôn sẵn sàng trong docker-compose nên mặc định bật load_db.
LOAD_DB = os.getenv("PIPELINE_LOAD_DB", "1") == "1"

SOURCES: list[str] = [
    s.strip() for s in os.getenv("PIPELINE_SOURCES", "itviec,topcv").split(",") if s.strip()
]

DEFAULT_ARGS = {
    "owner": "quangnguyen",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=30),
}

dag = None
if _AIRFLOW_AVAILABLE:
    with DAG(
        dag_id="jobs_daily",
        default_args=DEFAULT_ARGS,
        description="Daily pipeline: scrape→process→dashboard→db→kaggle (all sources)",
        schedule="0 0 * * *",
        start_date=datetime(2024, 1, 1),
        catchup=False,
        max_active_runs=1,
        tags=["jobs", "daily", "kaggle"],
        doc_md="""
## Jobs Daily (Airflow-only scheduler)

One pattern for every source (`pipeline/runner.py`):

```
scrape → process → dashboard → [load_db] → kaggle_push → cleanup
```

- Add a source: register adapter in `pipeline/sources/` + `PIPELINE_SOURCES`.
- Manual run: Airflow UI → `jobs_daily` → Trigger DAG (không dùng cron).
- Local test: `python -m pipeline run itviec --max-pages 2 --no-kaggle`
- Server: set `PROJECT_ROOT`, `DATA_ROOT` envs; no code change.
        """,
    ) as dag:
        start = EmptyOperator(task_id="start")

        source_tasks = []
        for src in SOURCES:
            # topcv raw nằm ở <DATA_ROOT>/raw/topcv (giữ layout cũ), còn lại <DATA_ROOT>/<src>
            data_dir = str(Path(DATA_ROOT) / ("raw/topcv" if src == "topcv" else src))
            flags = "--load-db" if LOAD_DB else "--no-kaggle"
            run_src = BashOperator(
                task_id=f"run_{src}",
                # push Kaggle mặc định bật trong runner (push_kaggle=True).
                bash_command=f"cd {PROJECT_ROOT} && {PYTHON} -m pipeline run {src} --data-dir {data_dir} {flags}".strip(),
                execution_timeout=timedelta(minutes=25),
            )
            source_tasks.append(run_src)

        def _notify(**context):
            import logging

            logging.info("=" * 60)
            logging.info("PIPELINE COMPLETE — %s", context["ds"])
            logging.info("sources: %s", SOURCES)
            logging.info("=" * 60)

        notify = PythonOperator(task_id="notify", python_callable=_notify)
        end = EmptyOperator(task_id="end")

        start >> source_tasks >> notify >> end
