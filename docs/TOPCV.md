# TopCV Scraper

## Overview
Scrapes IT job listings from topcv.vn using Playwright to bypass Cloudflare protection.

## Location
- **Server**: `/mnt/kaggle_data/topcv/`
- **Local**: `/Users/quangnguyen/startup/kaggle_pipeline/`

## Files

```
topcv/
├── scraper/
│   ├── __init__.py
│   └── topcv_scraper.py        # Main scraper
├── pipeline/
│   ├── __init__.py
│   ├── config.py               # Configuration
│   └── daily_pipeline.py       # Daily orchestration
├── dashboard/
│   └── app.py                  # Streamlit dashboard
├── data/
│   └── raw/topcv/              # Output data
└── requirements.txt
```

> Schedule duy nhất là Airflow DAG `jobs_daily` (không dùng cron).
> Chạy tay: `python -m pipeline run topcv`.

## Usage

### Run Scraper
```bash
cd /mnt/kaggle_data/topcv
source .venv/bin/activate
python pipeline/daily_pipeline.py
```

### Run Dashboard
```bash
cd /mnt/kaggle_data/topcv
source .venv/bin/activate
streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```

## Data Output

### Files
- `topcv_jobs_YYYYMMDD_HHMMSS.csv` - Timestamped CSV
- `topcv_jobs_YYYYMMDD_HHMMSS.json` - Timestamped JSON
- `topcv_jobs_latest.csv` - Latest CSV (for dashboard)
- `topcv_jobs_latest.json` - Latest JSON (for dashboard)

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

Edit `pipeline/config.py`:
```python
KAGGLE_USERNAME = "docutee"
KAGGLE_DATASET_NAME = "topcv-it-jobs-vietnam"
SCRAPE_MAX_PAGES = 50
SCRAPE_HEADLESS = True
```

## Schedule (Airflow — không dùng cron)
Daily 00:00 UTC = 07:00 ICT qua DAG `jobs_daily`
(`dags/jobs_daily.py`, task `run_topcv`). Trigger tay trên Airflow UI.

## Dependencies
- playwright
- beautifulsoup4
- lxml
- pandas
- streamlit
- plotly
- kaggle
