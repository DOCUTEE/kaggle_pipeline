# Infrastructure

PostgreSQL + Grafana + Airflow (scheduler duy nhất, không dùng cron).

## Quick Start

```bash
# Start all services (postgres, grafana, airflow-db, scheduler, webserver)
cd infra
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f grafana
docker compose logs -f postgres
docker compose logs -f airflow-scheduler
```

## Access

| Service  | URL                      | Credentials       |
|----------|--------------------------|-------------------|
| Airflow  | http://localhost:8080     | admin / admin     |
| Grafana  | http://localhost:3000     | admin / admin     |
| Postgres | localhost:5432           | pipeline / pipeline_dev_2024 |

## Load Data

```bash
# From project root
python -m pipeline.build process itviec --data-dir data/itviec_v4
python -m pipeline.build load-db itviec --data-dir data/itviec_v4

# Or combined
python -m pipeline.build all itviec --data-dir data/itviec_v4 --load-db

# Check DB status
python -m pipeline.db status
```

## Dashboards

- **ITviec Overview**: http://localhost:3000/d/itviec-overview
- Auto-provisioned from `grafana/dashboards/overview.json`

## Airflow DAG

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
