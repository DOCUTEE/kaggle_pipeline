# Unified Pipeline Pattern — 1 pattern cho mọi source (Airflow-only)

Từ 2026-09-18, mọi nguồn (itviec, topcv, ...) chạy **đúng 1 pattern 6 bước**,
schedule duy nhất bằng **Airflow DAG `jobs_daily`** (không dùng cron):

```
scrape → process → dashboard → [load_db] → kaggle_push → cleanup
```

Từ 2026-09-20, pattern được áp xuống **tận tầng implementation**: không chỉ
orchestration giống nhau, mà cả storage / transform / dashboard / db / publish
đều dùng chung 1 bộ code trong `pipeline/core/`.

## Sơ đồ

```
┌───────────────────────────────────────────────────────────────────┐
│  dags/jobs_daily.py                (Airflow scheduler duy nhất)   │
│  python -m pipeline run <source>   (chạy tay / debug)             │
│  scripts/run_pipeline.sh           (chạy tay, KHÔNG schedule)     │
└──────────────────────────────┬────────────────────────────────────┘
                               ▼
                  pipeline/runner.py::run_one()
        (6 bước, KHÔNG có if source == ... — source-agnostic)
                               │
                               ▼
            pipeline/sources/<ten>/adapter.py  ← implement BaseSource
            (kèm scraper.py · client.py · parser.py · models.py)
                               │
       ┌───────────────────────┼────────────────────────┐
       ▼                       ▼                        ▼
  pipeline/core/snapshot   pipeline/core/transform   pipeline/core/dashboard
  (atomic, dedup, latest)  (schema chuẩn + derived)  (1 shell + chart specs)
                               │
                               ▼
                     pipeline/db.py (loader generic theo DbSpec)
                     pipeline/core/publish.py (staging + Kaggle)
```

Mỗi source implement đúng 6 method:

| Method | Trách nhiệm | Code dùng chung |
|---|---|---|
| `scrape()` | scrape + ghi raw snapshot | `core/snapshot.py` |
| `process()` | raw → processed JSON | `core/transform.py` |
| `dashboard()` | processed → HTML | `core/dashboard.py` |
| `db_spec()` / `load_db()` | nạp Postgres | `pipeline/db.py` |
| `staging_files()` | file publish Kaggle | `core/publish.py` |

## Schema chuẩn (conformed)

Cả 2 nguồn ra **cùng tên file `processed_jobs.json`** với cùng cột core
(khai báo ở `pipeline/core/transform.py::PROCESSED_CORE_FIELDS`).
Dùng JSON thay CSV để giữ đúng kiểu dữ liệu (list/bool/số); dữ liệu phân tích
được query từ Postgres:

```
job_id, title, company, url, salary, location, location_clean,
skills, num_skills, skill_categories, seniority,
posted_date, posted_hours_ago, scraped_at, source
```

Cột đặc thù của từng nguồn vẫn được giữ thêm phía sau (itviec: `working_type`,
`label`, `job_function`, `highlights`; topcv: `is_hot`, `level`, `experience`,
`category`, `deadline`), nên vẫn join/so sánh chéo 2 nguồn được.

Snapshot raw cũ (`job_key`/`tags`/`posted_time`) vẫn process được nhờ
`LEGACY_ALIASES` trong `core/transform.py`.

## Thêm nguồn mới (vd `topdev`)

1. Tạo package `pipeline/sources/topdev/` theo ĐÚNG pattern chung:

   ```
   pipeline/sources/topdev/
   ├── __init__.py      # from ...adapter import TopdevSource; __all__ = [...]
   ├── adapter.py       # implement đủ 6 method của BaseSource
   ├── scraper.py       # phân trang + retry + dedup → trả (stats, jobs)
   ├── client.py        # I/O tới site
   ├── parser.py        # HTML → models
   └── models.py        # data model
   ```

   (xem `tests/test_runner.py::StubSource` làm mẫu tối giản)
2. Đăng ký 1 dòng trong `pipeline/sources/__init__.py`
   (`from pipeline.sources.topdev import TopdevSource`) + 1 entry trong
   `pipeline/settings.py::SOURCES`.
3. Xong — CLI/DAG/dashboard/db tự nhận source mới.
   `tests/test_sources.py` fail nếu thiếu file/bước nào (có test chốt shape của package).

## Vận hành chuẩn (Airflow)

```bash
# triển khai infra (postgres + grafana + airflow)
cd infra && docker compose up -d

# mở UI → bật/trigger DAG
# http://localhost:8080  (server: http://100.80.131.68:8080)
# DAG: jobs_daily, schedule 00:00 UTC = 07:00 ICT
```

## Chạy tay / debug (không schedule)

```bash
# liệt kê source
uv run python -m pipeline sources

# chạy 1 source (full 6 bước, push Kaggle mặc định bật)
uv run python -m pipeline run itviec
uv run python -m pipeline run topcv --max-pages 5 --no-kaggle   # test nhanh

# chạy tất cả
uv run python -m pipeline run all --load-db

# wrapper shell (manual only)
./scripts/run_pipeline.sh itviec --data-dir /mnt/kaggle_data/itviec --load-db

# server env (không sửa code khi đổi máy)
PROJECT_ROOT=/mnt/kaggle_data/kaggle_pipeline DATA_ROOT=/mnt/kaggle_data \
  uv run python -m pipeline run itviec --load-db
```

## Entrypoint duy nhất

Toàn bộ code legacy đã bị xoá (2026-09-20): `pipeline/daily_pipeline.py`,
`pipeline/config.py`, `pipeline/build.py`, `itviec/storage.py`, `itviec_scraper.py`,
`cli.py`, `itviec/__main__.py`, `kaggle_config/`. Chỉ còn **1 entrypoint**:

```bash
uv run python -m pipeline run itviec|topcv|all [--load-db] [--no-kaggle]
```

Không còn CLI `python -m pipeline.build`, `python -m pipeline.db`, `python -m itviec`.
Cron đã gỡ hoàn toàn: `scripts/daily_pipeline.sh` và `run_daily.sh` trên server
đã xóa, `deploy/setup_server.sh` tự gỡ crontab cũ khi deploy.

## Config duy nhất

`pipeline/settings.py` + env: `PROJECT_ROOT, DATA_ROOT, LOG_DIR, KAGGLE_USERNAME,`
`ITVIEC_KAGGLE_DATASET, TOPCV_KAGGLE_DATASET, DB_*, PIPELINE_SOURCES, PIPELINE_LOAD_DB`.
Local và server chỉ khác env.

## Test chốt pattern

```bash
python -m unittest discover -s tests -v
```

- `test_sources.py` — mọi source implement đủ 6 method, DbSpec khớp schema, runner không rẽ nhánh theo source.
- `test_runner.py` — đăng ký 1 source GIẢ rồi chạy `run_one()`; nếu runner còn hard-code itviec/topcv thì fail.
- `test_core.py` — transform/db-spec/dashboard/snapshot dùng chung.
