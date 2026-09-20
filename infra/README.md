# Infrastructure

PostgreSQL + Grafana là phần chạy mặc định.
Airflow nằm sau profile `airflow` (không chạy mặc định — scheduler chính là cron).

## Quick Start

```bash
# Mặc định: chỉ postgres + grafana
cd infra
docker compose up -d

# Bật thêm Airflow (UI + backfill, tốn ~1.25GB RAM)
docker compose --profile airflow up -d

# Check status
docker compose ps

# View logs
docker compose logs -f grafana
docker compose logs -f postgres
docker compose --profile airflow logs -f airflow-scheduler
```

## Access

| Service  | URL                      | Credentials       |
|----------|--------------------------|-------------------|
| Airflow  | http://localhost:8080     | admin / admin     |
| Grafana  | http://localhost:3000     | admin / admin     |
| Postgres | localhost:5432           | pipeline / pipeline_dev_2024 |

> Toàn bộ credentials lấy từ `infra/.env` (copy từ `.env.example`).
> Đổi password ở **một chỗ** — Postgres, Grafana datasource và Airflow đều đọc cùng env.

## Load Data

```bash
# From project root — 1 entrypoint duy nhất (process + dashboard + [load_db] + kaggle + cleanup)
python -m pipeline run itviec --load-db
python -m pipeline run topcv  --load-db
python -m pipeline run all    --load-db
```

## Dashboards

- **ITviec Overview**: http://localhost:3000/d/itviec-overview
- Auto-provisioned from `grafana/dashboards/overview.json`

## Airflow DAG (optional — không chạy mặc định)

- **DAG**: `jobs_daily` (dags/jobs_daily.py), schedule `0 0 * * *`
- Trigger tay: Airflow UI → `jobs_daily` → Trigger DAG
- Task logs: UI → task `run_itviec` / `run_topcv` → Logs

## Stop Services

```bash
cd infra
docker compose down

# Remove data (reset)
docker compose down -v
```
