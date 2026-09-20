# Infrastructure

Chỉ 2 service: **PostgreSQL** (kho dữ liệu) + **Grafana** (dashboard query trực tiếp Postgres).
Scheduler là **cron trên host** (`scripts/cron_daily.sh`) — không dùng Airflow.

## Quick Start

```bash
cd infra
cp .env.example .env      # điền POSTGRES_*, GF_*, KAGGLE_*
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f grafana
docker compose logs -f postgres
```

## Access

| Service  | URL                      | Credentials       |
|----------|--------------------------|-------------------|
| Grafana  | http://localhost:3000     | admin / admin     |
| Postgres | localhost:5432           | pipeline / pipeline_dev_2024 |

> Toàn bộ credentials lấy từ `infra/.env` (copy từ `.env.example`).
> Đổi password ở **một chỗ** — Postgres container và Grafana datasource đều đọc cùng env.

## Load Data

```bash
# From project root — 1 entrypoint duy nhất (scrape + process + dashboard + [load_db] + kaggle + cleanup)
python -m pipeline run itviec --load-db
python -m pipeline run topcv  --load-db
python -m pipeline run all    --load-db

# Hoặc chạy đúng cái cron chạy mỗi ngày:
./scripts/cron_daily.sh
```

## Dashboards

- **ITviec Overview**: http://localhost:3000/d/itviec-overview
- Auto-provisioned from `grafana/dashboards/overview.json`

## Schedule (cron trên host, không phải container)

```bash
crontab -l     # 0 7 * * * /mnt/kaggle_data/kaggle_pipeline/scripts/cron_daily.sh
```

Cài/ghi lại entry: `deploy/setup_server.sh` (hoặc `deploy/push_to_server.sh` tự thêm nếu thiếu).
Log: `logs/pipeline_YYYY-MM-DD.log` + `logs/cron.log`.

## Stop Services

```bash
cd infra
docker compose down

# Remove data (reset)
docker compose down -v
```
