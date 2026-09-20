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
| **Grafana** (query Postgres: `itviec_jobs`, `topcv_jobs`) | http://100.80.131.68:3000 |

> Dữ liệu phân tích được query trực tiếp từ **PostgreSQL** — không còn file CSV
> và không còn app Streamlit.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       CRON 07:00 ICT → scripts/cron_daily.sh      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  SCRAPE   │───▶│ PROCESS  │───▶│ DASHBOARD│          │
│  │ itviec +  │    │ Clean +  │    │ HTML +   │          │
│  │ topcv.vn  │    │ Engineer │    │ Plotly   │          │
│  └──────────┘    └──────────┘    └──────────┘          │
│       │               │                  │              │
│       ▼               ▼                  ▼              │
│  ┌──────────┐   ┌───────────┐    ┌──────────────┐      │
│  │ Raw JSON │   │ Postgres  │    │ Kaggle Push  │      │
│  │ snapshot │   │ → Grafana │    │ (JSON)       │      │
│  └──────────┘   └───────────┘    └──────────────┘      │
│                                                         │
│  Server: 100.80.131.68 (Ubuntu 24.04, 8GB RAM)         │
│  Storage: /mnt/kaggle_data/ (783GB)                     │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
kaggle_pipeline/
├── pipeline/                       # Unified pipeline — 1 pattern cho mọi source
│   ├── cli.py / __main__.py        #   entrypoint: python -m pipeline run itviec|topcv|all
│   ├── runner.py                   #   6 bước, source-agnostic (không if source == ...)
│   ├── settings.py                 #   config duy nhất (env-overridable)
│   ├── db.py                       #   1 loader Postgres generic (theo DbSpec)
│   ├── kaggle_check.py             #   preflight creds trước khi push
│   ├── core/                       #   hạ tầng dùng chung, không biết gì về source
│   │   ├── contracts.py            #     ScrapeResult / ProcessResult / DbSpec / BaseSource
│   │   ├── snapshot.py             #     ghi raw: atomic + dedup + *_latest
│   │   ├── transform.py            #     schema chuẩn + derived features + skill taxonomy
│   │   ├── dashboard.py            #     1 HTML shell + chart primitives
│   │   └── publish.py              #     staging + push Kaggle
│   └── sources/                    #   adapter: base.py (contract), itviec.py, topcv.py
│
├── sources/ (trong pipeline/)       # mỗi source 1 package, cùng tên file, cùng tầng
│   ├── itviec/  adapter · client · models · parser · scraper    (requests + BS4)
│   └── topcv/   adapter · client · models · parser · scraper    (Playwright)
│
├── scripts/cron_daily.sh           # SCHEDULER: cron 07:00 (retry+log+flock+exit code)
├── infra/                          # docker compose: postgres + grafana (scheduler là cron)
├── deploy/                         # deploy thủ công lên server
├── scripts/run_pipeline.sh         # chạy tay / debug (không schedule)
├── tests/                          # unittest offline: core + contract + runner (CI chạy trước khi deploy)
└── data/                           # raw JSON snapshot + processed_jobs.json (<source>/...)
```

> Mỗi source là 1 package `pipeline/sources/<ten>/` cùng tên file, cùng tầng;
> storage,
> transform, dashboard, db, publish đều dùng chung ở `pipeline/core/`.
> Chi tiết: `docs/PIPELINE_PATTERN.md`.

---

## 🚀 Quick Start

### Development Workflow

```bash
# 1. Dev ở local
cd /Users/quangnguyen/startup/kaggle_pipeline
source .venv/bin/activate
python -m pipeline run itviec --max-pages 2 --no-kaggle   # test nhanh

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

# Run scraper (full 6 bước)
uv run python -m pipeline run topcv

# Xem dữ liệu: query Postgres qua Grafana
cd infra && docker compose up -d   # Grafana: http://localhost:3000
```

### Server Management

```bash
# SSH to server
ssh docutee@100.80.131.68

# Navigate to pipeline repo
cd /mnt/kaggle_data/kaggle_pipeline

# Activate venv
source .venv/bin/activate

# Run scraper manually
python -m pipeline run itviec --data-dir /mnt/kaggle_data/itviec --load-db
python -m pipeline run topcv  --data-dir /mnt/kaggle_data/raw/topcv --load-db

# View logs
tail -f logs/pipeline_*.log

# Xem dữ liệu (Grafana query Postgres)
docker compose -f infra/docker-compose.yml up -d
```

---

## ⚙️ TopCV Scraper

### Features
- ✅ Playwright-based (bypasses Cloudflare)
- ✅ Paginated scraping
- ✅ Daily automation bằng cron (`scripts/cron_daily.sh`)
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
/mnt/kaggle_data/                  # Main data partition
├── kaggle_pipeline/               # Repo code (rsync từ CI)
├── itviec/                        # Raw output ITviec
├── raw/topcv/                     # Raw output TopCV
└── logs/                          # Shared logs
```

### Schedule (cron — scheduler chính)
```bash
# cron 07:00 mỗi ngày: scripts/cron_daily.sh (retry + log + flock)
crontab -l
tail -f logs/pipeline_$(date +%F).log      # log của lần chạy

# Chạy tay ngay (cùng code path với cron):
./scripts/cron_daily.sh
```

### Deploy Workflow
```bash
# 1. Push code from local to server
./deploy/push_to_server.sh

# 2. Setup server (first time only)
./deploy/setup_server.sh
```

### Grafana Dashboard (query Postgres)
- **URL**: http://100.80.131.68:3000 (admin/admin)
- **Nguồn dữ liệu**: PostgreSQL `kaggle_pipeline` — bảng `itviec_jobs`, `topcv_jobs`
- **Pipeline nạp DB**: `python -m pipeline run <source> --load-db`
- **Auto-provision**: `infra/grafana/dashboards/overview.json`

### Manual Commands
```bash
# SSH
ssh docutee@100.80.131.68

# Run TopCV scraper
cd /mnt/kaggle_data/kaggle_pipeline && source .venv/bin/activate \
  && python -m pipeline run topcv --data-dir /mnt/kaggle_data/raw/topcv --load-db

# View logs
tail -f logs/pipeline_topcv_$(date +%F).log

# Query dữ liệu
docker exec -it kaggle_postgres psql -U pipeline -d kaggle_pipeline -c "SELECT COUNT(*) FROM itviec_jobs;"
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
| **One pattern per source** | Mỗi source là 1 package `pipeline/sources/<ten>/` (`adapter/scraper/client/parser/models.py`) implement 6 method; storage/transform/dashboard/db/publish dùng chung ở `pipeline/core/`. Runner không có `if source == ...` |
| **Conformed schema** | Cả 2 nguồn ra `processed_jobs.json` cùng cột core (`job_id, title, company, salary, location_clean, skills, seniority, posted_hours_ago, skill_categories, ...`) → join/so sánh chéo được |
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
| **Grafana không có dữ liệu** | Chạy `--load-db`; kiểm tra `docker compose ps` (postgres healthy) |
| **Disk full** | Old data auto-cleaned after 30 days |

---

## 📄 License

MIT License — use freely, attribution appreciated.

---

## 🙏 Credits

- Data sources: [itviec.com](https://itviec.com), [topcv.vn](https://topcv.vn)
- Dashboard: [Grafana](https://grafana.com/) (query Postgres), [Plotly](https://plotly.com/python/) (HTML tĩnh)
- Scraping: [Playwright](https://playwright.dev/), [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)
