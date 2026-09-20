# TopCV Scraper

## Overview
Scrapes IT job listings from topcv.vn using Playwright to bypass Cloudflare protection.

Source package: `pipeline/sources/topcv/` — cùng pattern với itviec:
`adapter.py` (6 bước) · `scraper.py` (phân trang/retry) · `client.py` (Playwright)
· `parser.py` (HTML → Job) · `models.py` (Job dataclass).

## Files

```
pipeline/sources/topcv/
├── adapter.py                  # implement BaseSource (6 bước)
├── scraper.py                  # phân trang + delay + retry + dedup
├── client.py                   # Playwright: browser, chờ Cloudflare, lấy HTML
├── parser.py                   # HTML → Job (test offline được)
└── models.py                   # Job dataclass
pipeline/settings.py            # config: SOURCES["topcv"]
data/raw/topcv/                 # output: raw JSON + dashboard/processed_jobs.json
```

> Schedule: cron 07:00 hàng ngày (`scripts/cron_daily.sh`).
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

## Schedule (cron)
Daily 07:00 ICT qua `scripts/cron_daily.sh` (chạy `python -m pipeline run topcv --load-db`).
Chạy tay: `./scripts/cron_daily.sh` hoặc `python -m pipeline run topcv`.

## ⚠️ Giới hạn: Cloudflare chặn phân trang

Đo trực tiếp 2026-09-20: `?page=2` (và mọi page sau) trả trang
`Attention Required! | Cloudflare` (~4.8KB, 0 job) — **không phụ thuộc delay**
(đã thử 3s → 45s) và click link phân trang cũng bị chặn. Page 1 thì tải bình
thường (~1.9MB, 50 job).

Vì vậy `default_max_pages = 1` cho topcv: mỗi ngày lấy **50 job mới nhất**;
các job trùng được upsert theo `job_id` trong Postgres nên dữ liệu vẫn tích luỹ
theo thời gian. Code vẫn hỗ trợ nhiều page (`--max-pages N`) — khi có proxy
hoặc Cloudflare nới lỏng thì chỉ cần tăng tham số, không phải sửa code.

## Dependencies
- playwright
- beautifulsoup4
- lxml
- pandas
- plotly
- psycopg2-binary
- kaggle
