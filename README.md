# 🇻🇳 Vietnam IT Job Market Pipeline

> End-to-end data pipeline: **Scrape → Process → Visualize → Publish**
> Auto-collects IT job listings from [itviec.com](https://itviec.com) and [topcv.vn](https://topcv.vn) daily, builds interactive dashboards, and pushes datasets to Kaggle.

[![Kaggle Dataset - ITviec](https://img.shields.io/badge/Kaggle-ITviec-blue?logo=kaggle)](https://www.kaggle.com/datasets/quangcrawler/itviec-jobs)
[![Kaggle Dataset - TopCV](https://img.shields.io/badge/Kaggle-TopCV-green?logo=kaggle)](https://www.kaggle.com/datasets/docutee/topcv-it-jobs-vietnam)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-green)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📊 Live Dashboard

| Dashboard | URL |
|-----------|-----|
| **ITviec Dashboard** | http://100.80.131.68:8501 |
| **TopCV Dashboard** | http://100.80.131.68:8501 |

> [Open Dashboard →](http://100.80.131.68:8501)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│              AIRFLOW DAG jobs_daily (00:00 UTC = 07:00 ICT)       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  SCRAPE   │───▶│ PROCESS  │───▶│ DASHBOARD│          │
│  │ itviec +  │    │ Clean +  │    │ Streamlit│          │
│  │ topcv.vn  │    │ Engineer │    │ + Plotly │          │
│  └──────────┘    └──────────┘    └──────────┘          │
│       │                                  │              │
│       ▼                                  ▼              │
│  ┌──────────┐                    ┌──────────┐          │
│  │ Raw Data │                    │  Kaggle  │          │
│  │ CSV/JSON │                    │  Push    │          │
│  └──────────┘                    └──────────┘          │
│                                                         │
│  Server: 100.80.131.68 (Ubuntu 24.04, 8GB RAM)         │
│  Storage: /mnt/kaggle_data/ (783GB)                     │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
/mnt/kaggle_data/
├── itviec/                         # ITviec scraper
│   ├── client.py
│   ├── parser.py
│   ├── models.py
│   └── ...
│
├── topcv/                          # TopCV scraper (NEW)
│   ├── scraper/
│   │   ├── __init__.py
│   │   └── topcv_scraper.py        # Playwright-based scraper
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── config.py               # Configuration
│   │   └── daily_pipeline.py       # Daily orchestration
│   ├── dashboard/
│   │   └── app.py                  # Streamlit dashboard
│   ├── data/
│   │   └── raw/topcv/              # Scraped data
│   └── requirements.txt
│
└── logs/                           # Shared logs
    └── topcv_pipeline.log
```

---

## 🚀 Quick Start

### Development Workflow

```bash
# 1. Dev ở local
cd /Users/quangnguyen/startup/kaggle_pipeline
source .venv/bin/activate
python pipeline/daily_pipeline.py  # Test locally

# 2. Push code lên server
./deploy/push_to_server.sh

# 3. Deploy trên server
./deploy/setup_server.sh
```

### Local Development (uv)

```bash
# Install dependencies (uv quản lý .venv + uv.lock)
uv sync
uv run playwright install chromium

# Thêm/sửa dep: sửa pyproject.toml rồi
uv add <package>            # hoặc sửa tay pyproject.toml + uv sync
uv export --frozen --format requirements-txt --no-hashes -o requirements.txt  # giữ cho deploy server (pip)

# Run scraper
uv run python pipeline/daily_pipeline.py

# Run dashboard
uv run streamlit run dashboard/app.py --server.port 8501
```

### Server Management

```bash
# SSH to server
ssh docutee@100.80.131.68

# Navigate to topcv pipeline
cd /mnt/kaggle_data/topcv

# Activate venv
source .venv/bin/activate

# Run scraper manually
python pipeline/daily_pipeline.py

# View logs
tail -f /mnt/kaggle_data/logs/topcv_pipeline.log

# Restart dashboard
pkill -f streamlit
streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
```

---

## ⚙️ TopCV Scraper

### Features
- ✅ Playwright-based (bypasses Cloudflare)
- ✅ Paginated scraping
- ✅ Daily Airflow automation (DAG jobs_daily)
- ✅ Streamlit dashboard
- ✅ Kaggle integration (when configured)

### Data Fields

| Field | Description |
|-------|-------------|
| `job_id` | Unique identifier |
| `title` | Job title |
| `company` | Company name |
| `salary` | Salary range |
| `location` | City/location |
| `experience` | Required experience |
| `level` | Job level |
| `skills` | Required skills |
| `posted_date` | When posted |
| `url` | Job listing URL |

---

## 🖥️ Server Deployment

### Info
| | |
|---|---|
| **IP** | `100.80.131.68` |
| **OS** | Ubuntu 24.04 LTS |
| **Spec** | 8GB RAM, 1TB disk |
| **User** | `docutee` |
| **Password** | `12032512` |

### Directory Layout
```
/mnt/kaggle_data/           # Main data partition
├── itviec/                 # ITviec pipeline
├── topcv/                  # TopCV pipeline
└── logs/                   # Shared logs
```

### Airflow Schedule (scheduler duy nhất, không dùng cron)
```bash
# DAG jobs_daily — 00:00 UTC daily (= 07:00 ICT)
# Triển khai: cd infra && docker compose up -d
# Trigger tay: http://100.80.131.68:8080 → jobs_daily → Trigger DAG
```

### Deploy Workflow
```bash
# 1. Push code from local to server
./deploy/push_to_server.sh

# 2. Setup server (first time only)
./deploy/setup_server.sh
```

### Streamlit Dashboard
- **Status**: Running on port 8501
- **URL**: http://100.80.131.68:8501
- **Process**: `streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0`

### Manual Commands
```bash
# SSH
ssh docutee@100.80.131.68

# Run TopCV scraper
cd /mnt/kaggle_data/topcv && source .venv/bin/activate && python pipeline/daily_pipeline.py

# View logs
tail -f /mnt/kaggle_data/logs/topcv_pipeline.log

# Restart dashboard
pkill -f streamlit
cd /mnt/kaggle_data/topcv && source .venv/bin/activate && streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
```

---

## 📦 Kaggle Dataset

### ITviec Dataset
| | |
|---|---|
| **URL** | [kaggle.com/datasets/quangcrawler/itviec-jobs](https://www.kaggle.com/datasets/quangcrawler/itviec-jobs) |
| **Update** | Daily at 7:00 AM |

### TopCV Dataset
| | |
|---|---|
| **URL** | [kaggle.com/datasets/docutee/topcv-it-jobs-vietnam](https://www.kaggle.com/datasets/docutee/topcv-it-jobs-vietnam) |
| **Update** | Daily at 6:00 AM |
| **Status** | ⚠️ Requires valid Kaggle API key |

### Setup Kaggle API Key
```bash
# On server
mkdir -p ~/.kaggle
cat > ~/.kaggle/kaggle.json << 'EOF'
{
  "username": "docutee",
  "key": "YOUR_KAGGLE_API_KEY"
}
EOF
chmod 600 ~/.kaggle/kaggle.json
```

---

## 📋 Data Schema

### TopCV Fields

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | TopCV job ID |
| `url` | string | Job detail URL |
| `title` | string | Job title |
| `company` | string | Company name |
| `company_url` | string | Company profile URL |
| `salary` | string | Salary range |
| `location` | string | City |
| `experience` | string | Required experience |
| `level` | string | Job level |
| `job_type` | string | Employment type |
| `category` | string | Job category |
| `skills` | list | Required skills |
| `posted_date` | string | When posted |
| `deadline` | string | Application deadline |
| `is_hot` | bool | Hot job badge |
| `is_urgent` | bool | Urgent hiring |
| `scrape_date` | string | Scrape date |

---

## 🛡️ Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Respect robots.txt** | Verified allowed; polite rate limiting with jitter |
| **Cloudflare bypass** | Playwright browser automation |
| **Atomic writes** | Temp file + `os.replace()` prevents corruption |
| **Idempotent runs** | Dedup by job_id; re-runs overwrite same snapshot |
| **Error handling** | Retry with backoff, fail gracefully |

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| **Playwright not working** | `playwright install chromium` |
| **0 jobs scraped** | Check if topcv.vn blocked; may need to update selectors |
| **Kaggle auth failed** | Re-generate API key at kaggle.com/settings/api |
| **Dashboard not accessible** | Check port 8501 is open; `ps aux | grep streamlit` |
| **Disk full** | Old data auto-cleaned after 30 days |

---

## 📄 License

MIT License — use freely, attribution appreciated.

---

## 🙏 Credits

- Data sources: [itviec.com](https://itviec.com), [topcv.vn](https://topcv.vn)
- Dashboard: [Streamlit](https://streamlit.io/), [Plotly](https://plotly.com/python/)
- Scraping: [Playwright](https://playwright.dev/), [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)
