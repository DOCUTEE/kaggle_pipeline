# 🇻🇳 ITviec Job Market Pipeline

> End-to-end data pipeline: **Scrape → Process → Visualize → Publish**
> Auto-collects all IT job listings from [itviec.com](https://itviec.com) daily, builds interactive dashboards, and pushes datasets to Kaggle.

[![Kaggle Dataset](https://img.shields.io/badge/Kaggle-Dataset-blue?logo=kaggle)](https://www.kaggle.com/datasets/quangcrawler/itviec-jobs)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-green)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📊 Live Dashboard Preview

| KPI | Insight |
|-----|---------|
| **719** Total Jobs | From **137** companies across **9** cities |
| **54%** Ho Chi Minh | Dominant tech hub |
| **48%** Senior+ Roles | Senior-heavy market |
| **2.9%** Remote | Office-first culture |

> [Open Dashboard →](dashboard/itviec_dashboard.html) *(self-contained HTML, no server needed)*

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    DAILY CRON (7AM)                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │  SCRAPE   │───▶│ PROCESS  │───▶│ DASHBOARD│          │
│  │ itviec.com│    │ Clean +  │    │  Plotly  │          │
│  │  36 pages │    │ Engineer │    │ 12 charts│          │
│  └──────────┘    └──────────┘    └──────────┘          │
│       │                                  │              │
│       ▼                                  ▼              │
│  ┌──────────┐                    ┌──────────┐          │
│  │ Raw Data │                    │  HTML +  │          │
│  │ CSV/JSON │                    │  Kaggle  │          │
│  │ Parquet  │                    │  Push    │          │
│  └──────────┘                    └──────────┘          │
│                                                         │
│  Server: 100.80.131.68 (Ubuntu 24.04, 8GB RAM)         │
│  Storage: /mnt/kaggle_data/ (783GB)                     │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
kaggle_pipeline/
├── itviec/                     # Scraper package
│   ├── client.py               # HTTP client (rate limit, retry, backoff)
│   ├── parser.py               # BeautifulSoup HTML → Pydantic models
│   ├── models.py               # Data contracts (Job, WorkingType, Label)
│   ├── runner.py               # Orchestrator (sequential/parallel)
│   ├── storage.py              # Atomic writes (CSV/JSON/Parquet)
│   └── __main__.py             # Entry point
│
├── dashboard/                  # Analytics
│   ├── process_data.py         # Data cleaning + feature engineering
│   └── build_dashboard.py      # Plotly dashboard generator
│
├── scripts/
│   └── daily_pipeline.sh       # Cron automation script
│
├── data/                       # Local data snapshots
│   └── itviec_v4/
│       ├── itviec_jobs_latest.csv
│       ├── itviec_jobs_latest.json
│       └── itviec_jobs_latest.parquet
│
├── cli.py                      # CLI entry point (Typer)
└── README.md
```

---

## 🚀 Quick Start

### Local Development

```bash
# Clone
git clone <repo-url> && cd kaggle_pipeline

# Install deps
pip install typer requests beautifulsoup4 pydantic tenacity pandas plotly kaleido

# Run full pipeline
python -m itviec --output data/itviec_v4 --workers 4
python dashboard/process_data.py data/itviec_v4
python dashboard/build_dashboard.py data/itviec_v4

# Open dashboard
open data/itviec_v4/itviec_dashboard.html
```

### One-Liner

```bash
python -m itviec -o data/itviec_v4 -w 4 && python dashboard/process_data.py data/itviec_v4 && python dashboard/build_dashboard.py data/itviec_v4 && open data/itviec_v4/itviec_dashboard.html
```

---

## ⚙️ CLI Options

```bash
python -m itviec [OPTIONS]

Options:
  --output, -o PATH        Output directory (default: data/itviec)
  --workers, -w INT        Parallel workers 1-16 (default: 1)
  --max-pages INT          Cap pages for testing
  --min-delay FLOAT        Min delay between requests in seconds (default: 0.8)
  --max-delay FLOAT        Max delay between requests in seconds (default: 2.0)
  --timeout INT            HTTP timeout in seconds (default: 30)
  --no-csv                 Skip CSV output
  --no-json                Skip JSON output
  --parquet                Also write Parquet
  --fail-threshold FLOAT   Max empty required field ratio (default: 0.5)
  --verbose, -v            Debug logging
```

---

## 📈 Dashboard Features

The generated dashboard includes **12 interactive Plotly charts** with glass morphism UI:

| Section | Charts |
|---------|--------|
| **KPIs** | Total jobs, companies, cities, hot jobs, remote %, senior+ % |
| **📍 Geographic** | Jobs by location, Working type × location |
| **👤 Profile** | Seniority donut, Work mode, Job urgency, Job freshness |
| **🛠️ Skills** | Top 20 skills, Skill categories, Skill co-occurrence heatmap |
| **🏢 Companies** | Top 15 hiring companies, Seniority × location, Skills × seniority heatmap |

---

## 🔄 Data Processing Pipeline

### Step 1: Cleaning
- Remove "Sign in to view salary" placeholders
- Normalize locations (HCM, Ha Noi, Da Nang, multi-city)
- Parse relative posted times → hours

### Step 2: Feature Engineering
- **Seniority extraction**: Intern → Manager+ from title patterns + YoE parsing
- **Skill taxonomy**: Map 200+ raw tags into 9 categories (Languages, Frontend, Backend, Database, Cloud & DevOps, Data & AI, Mobile, Testing, Soft Skills)
- **Quality checks**: Fail loudly if >50% of cards have missing required fields

### Step 3: Storage
- Atomic writes (temp file → rename) prevents corruption
- Dedup by `job_key` or `url`
- Snapshot per run + `*_latest.*` symlink

---

## 🗺️ Skill Categories

| Category | Tags | Example |
|----------|------|---------|
| **Languages** | Python, Java, JavaScript, TypeScript, Go, Rust | Core programming |
| **Frontend** | React, Vue, Angular, Next.js, Tailwind | UI frameworks |
| **Backend** | Node.js, Django, Spring Boot, .NET, FastAPI | Server-side |
| **Database** | PostgreSQL, MongoDB, Redis, Elasticsearch | Data storage |
| **Cloud & DevOps** | AWS, Azure, Docker, Kubernetes, CI/CD | Infrastructure |
| **Data & AI** | ML, Spark, Kafka, NLP, LLM, GenAI | Data/ML stack |
| **Mobile** | iOS, Android, Flutter, React Native | Mobile dev |
| **Testing** | Selenium, Cypress, QA/QC, Automation | Quality assurance |
| **Soft Skills** | Agile, Scrum, English, Project Management | Process/culture |

---

## 🖥️ Server Deployment

### Info
| | |
|---|---|
| **IP** | `100.80.131.68` |
| **OS** | Ubuntu 24.04 LTS |
| **Spec** | 8GB RAM, 1TB disk |
| **Data** | `/mnt/kaggle_data/itviec/` (783GB partition) |
| **User** | `docutee` |

### Cron Schedule
```bash
# Runs daily at 7:00 AM (ICT)
0 7 * * * /home/docutee/kaggle_pipeline/scripts/daily_pipeline.sh >> /mnt/kaggle_data/logs/cron.log 2>&1
```

### Manual Run
```bash
ssh docutee@100.80.131.68
bash ~/kaggle_pipeline/scripts/daily_pipeline.sh
```

### Logs
```bash
# Pipeline logs
cat /mnt/kaggle_data/logs/pipeline_YYYY-MM-DD.log

# Cron logs
cat /mnt/kaggle_data/logs/cron.log
```

---

## 📦 Kaggle Dataset

| | |
|---|---|
| **URL** | [kaggle.com/datasets/quangcrawler/itviec-jobs](https://www.kaggle.com/datasets/quangcrawler/itviec-jobs) |
| **Files** | `itviec_jobs.csv`, `itviec_jobs.json`, `processed_jobs.csv` |
| **Update** | Daily at 7:00 AM (auto) |
| **License** | CC0-1.0 |

### Push Manually
```bash
export KAGGLE_API_TOKEN="your-key"
export KAGGLE_USERNAME="your-username"
kaggle datasets create -p /mnt/kaggle_data/itviec/kaggle_upload --dir-mode zip
```

---

## 🛡️ Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Respect robots.txt** | Verified allowed; polite rate limiting with jitter |
| **Never retry 401/403** | Stop immediately on access denial |
| **Atomic writes** | Temp file + `os.replace()` prevents corruption |
| **Fail loudly** | `ParsingQualityError` when markup changes |
| **Idempotent runs** | Dedup by job_key; re-runs overwrite same snapshot |
| **Resumable** | Sequential processing; crash mid-run doesn't lose data |

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| **0 jobs scraped** | Check `Accept-Encoding` — remove `br` if brotli not installed |
| **Parse quality error** | Site markup changed — update CSS selectors in `parser.py` |
| **403 Access denied** | itviec.com blocked access; may need to rotate User-Agent |
| **429 Rate limited** | Increase `--min-delay` and `--max-delay` |
| **Kaggle auth failed** | Re-generate API key at kaggle.com/settings/api |
| **Disk full** | Old data auto-cleaned after 30 days; check `/mnt/kaggle_data/logs` |

---

## 📋 Data Schema

<details>
<summary>Click to expand full schema</summary>

### Raw Fields

| Field | Type | Description |
|-------|------|-------------|
| `job_key` | string | Stable UUID from `data-job-key` |
| `url` | string | Job detail URL |
| `title` | string | Job title |
| `company` | string | Company name |
| `salary` | string | Salary (login-gated) |
| `job_function` | string | Job category |
| `working_type` | enum | Remote / Hybrid / At office |
| `location` | string | City |
| `tags` | list | Skill tags |
| `posted_time` | string | Relative time |
| `label` | enum | SUPER HOT / HOT / None |
| `highlights` | list | Company highlights |
| `page` | int | Listing page |
| `scraped_at` | string | ISO-8601 timestamp |

### Processed Fields

| Field | Type | Description |
|-------|------|-------------|
| `seniority` | enum | Intern → Manager+ |
| `posted_hours_ago` | float | Hours since posted |
| `skill_categories` | list | Mapped categories |
| `location_clean` | string | Normalized city |
| `num_tags` | int | Tag count |
| `has_highlights` | bool | Has highlights |

</details>

---

## 📄 License

MIT License — use freely, attribution appreciated.

---

## 🙏 Credits

- Data source: [itviec.com](https://itviec.com) — Vietnam's #1 IT job board
- Dashboard: [Plotly](https://plotly.com/python/) interactive charts
- Scraping: [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + [requests](https://docs.python-requests.com/)
- Data contracts: [Pydantic](https://docs.pydantic.dev/)
