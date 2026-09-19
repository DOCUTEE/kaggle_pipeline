# TopCV Scraper

## Overview
Scrapes IT job listings from topcv.vn using Playwright to bypass Cloudflare protection.

Adapter: `pipeline/sources/topcv.py` (bọc `scraper/topcv_scraper.py` theo `BaseSource`).

## Files

```
scraper/
└── topcv_scraper.py            # Main scraper (Playwright)
pipeline/
├── sources/topcv.py            # Adapter cho runner
└── settings.py                 # Config (SOURCES["topcv"])
data/raw/topcv/                 # Output data (mặc định): raw JSON + dashboard/processed_jobs.json
```

> Schedule duy nhất là Airflow DAG `jobs_daily` (không dùng cron).
> Chạy tay: `python -m pipeline run topcv`.

## Usage

### Run Scraper
```bash
cd /mnt/kaggle_data/kaggle_pipeline
source .venv/bin/activate
python -m pipeline run topcv --max-pages 5   # bỏ --max-pages để scrape 50 pages
```

### Xem dữ liệu
Không còn app Streamlit — query Postgres qua Grafana (http://localhost:3000):

```bash
python -m pipeline run topcv --load-db
```

## Data Output

### Files
- `topcv_jobs_YYYYMMDD_HHMMSS.json` — snapshot raw (đầy đủ kiểu dữ liệu)
- `topcv_jobs_latest.json` — bản mới nhất (input của bước process)
- `dashboard/processed_jobs.json` — schema chuẩn, nạp Postgres + publish Kaggle

### Fields
| Field | Description |
|-------|-------------|
| `job_id` | TopCV job ID |
| `title` | Job title |
| `company` | Company name |
| `salary` | Salary range |
| `location` | City |
| `experience` | Required experience |
| `level` | Job level |
| `skills` | Required skills |
| `posted_date` | When posted |
| `url` | Job listing URL |

## Configuration

Sửa `pipeline/settings.py` (entry `SOURCES["topcv"]`) hoặc override bằng env:
`TOPCV_KAGGLE_DATASET`, `TOPCV_RAW_SUBDIR`, `DATA_ROOT`.

## Schedule (Airflow — không dùng cron)
Daily 00:00 UTC = 07:00 ICT qua DAG `jobs_daily`
(`dags/jobs_daily.py`, task `run_topcv`). Trigger tay trên Airflow UI.

## Dependencies
- playwright
- beautifulsoup4
- lxml
- pandas
- plotly
- psycopg2-binary
- kaggle
