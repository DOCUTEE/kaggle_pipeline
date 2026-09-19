# Unified Pipeline Pattern — 1 pattern cho mọi source (Airflow-only)

Từ 2026-09-18, mọi nguồn (itviec, topcv, ...) chạy **đúng 1 pattern 6 bước**,
schedule duy nhất bằng **Airflow DAG `jobs_daily`** (không dùng cron):

```
scrape → process → dashboard → [load_db] → kaggle_push → cleanup
```

## Sơ đồ

```
┌──────────────────────────────────────────────────────────────┐
│  dags/jobs_daily.py              (Airflow scheduler duy nhất) │
│  uv run python -m pipeline run <source> (chạy tay / debug)           │
│  scripts/run_pipeline.sh         (chạy tay, KHÔNG schedule)   │
└─────────────────────────┬────────────────────────────────────┘
                          ▼
             pipeline/runner.py::run_one()
                          │
   ┌──────────────────────┼──────────────────────────────────┐
   ▼                      ▼                                  ▼
 scrape              process/dashboard              load_db/kaggle/cleanup
 (adapter)           (pipeline/build.py)            (pipeline/db.py + build.py)
   │
   ▼
 pipeline/sources/<ten>.py  (implement BaseSource)
 pipeline/sources/base.py   (contract ScrapeResult)
 pipeline/settings.py       (config duy nhất, env-overridable)
```

## Thêm nguồn mới (vd `topdev`)

1. Tạo `pipeline/sources/topdev.py` implement `scrape(data_dir, ...)` trả `ScrapeResult`.
2. Đăng ký 1 dòng trong `pipeline/sources/__init__.py` + 1 entry trong `pipeline/settings.py::SOURCES`.
3. Xong — CLI/DAG tự nhận source mới, không sửa gì thêm.

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

## File legacy (vẫn chạy, nhưng không phát triển thêm)

| File | Thay bằng |
|---|---|
| `pipeline/daily_pipeline.py` (topcv-only) | `uv run python -m pipeline run topcv` |
| `pipeline/config.py` | `pipeline/settings.py` (file này giờ là shim re-export) |

Cron đã gỡ hoàn toàn: `scripts/daily_pipeline.sh` và `run_daily.sh` trên server
đã xóa, `deploy/setup_server.sh` tự gỡ crontab cũ khi deploy.

## Config duy nhất

`pipeline/settings.py` + env: `PROJECT_ROOT, DATA_ROOT, LOG_DIR, KAGGLE_USERNAME,`
`ITVIEC_KAGGLE_DATASET, TOPCV_KAGGLE_DATASET, DB_*, PIPELINE_SOURCES, PIPELINE_LOAD_DB`.
Local và server chỉ khác env.
