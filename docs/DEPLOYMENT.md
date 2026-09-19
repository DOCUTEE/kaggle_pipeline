# Deployment Guide (Airflow-only)

## Server Info
- **IP**: 100.80.131.68
- **OS**: Ubuntu 24.04 LTS
- **User**: docutee
- **Password**: 12032512

## Directory Structure
```
/mnt/kaggle_data/
├── kaggle_pipeline/    # repo (code + dags + infra)
├── itviec/             # ITviec data
├── raw/topcv/          # TopCV data
└── logs/               # Shared logs
```

## SSH Access
```bash
ssh docutee@100.80.131.68
# Password: 12032512
```

## Deploy
```bash
# Từ local: sync code + gỡ cron cũ + dựng infra + start dashboard
./deploy/setup_server.sh
```

Chi tiết xem `deploy/setup_server.sh`: sync code tới
`/mnt/kaggle_data/kaggle_pipeline`, xóa crontab legacy, chạy
`infra/docker-compose.yml` (postgres + grafana + airflow).

## CI/CD — chỉ `main` mới test + deploy, làm hàng ngày ở `develop`

| Branch | CI chạy gì |
|---|---|
| `develop` (default làm việc) | Không chạy gì — push thoải mái |
| PR `develop` → `main` | Chạy **test** (báo xanh/đỏ ngay trên PR, không deploy) |
| Push/`merge` vào `main` | Chạy **test** → xanh mới **deploy** |

```bash
git checkout develop
# ... code ...
git add -A && git commit -m "..." && git push origin develop
# mở PR develop -> main trên GitHub, chờ test xanh rồi Merge
```

Khuyên bật thêm branch protection cho `main` (GitHub → Settings → Branches →
Add rule): Require a pull request + Require status checks (`test`). Khi đó code
dở/test đỏ không thể merge lên `main` = không bao giờ deploy bậy.

Workflow `.github/workflows/deploy.yml` chạy mỗi khi push lên `main` qua 2 lớp:
1. **test** — `pip install -r requirements.txt` + `python -m unittest discover -s tests -v`
   (Python 3.12 khớp server, offline, ~15s). Đỏ thì deploy không bao giờ chạy.
2. **deploy** (`needs: [test]`) — rsync code (trừ `data/` + `logs/` + `.venv`
   để không đè mất dataset server đang cào) → `docker compose up -d` →
   reinstall deps → restart Streamlit → health check `:8080` + `:8501`.

Chạy test ở local trước khi push: `python -m unittest discover -s tests -v`.
Bỏ qua 1 lần deploy: thêm `[skip deploy]` vào commit message (thêm
`[skip test]` để bỏ qua cả lớp test — chỉ dùng khi cần).

### Secrets cần tạo (GitHub repo → Settings → Secrets and variables → Actions)

| Secret | Giá trị |
|---|---|
| `SERVER_HOST` | `100.80.131.68` |
| `SERVER_USER` | `docutee` |
| `SERVER_PASSWORD` | password SSH (= password sudo docker) |
| `TAILSCALE_AUTHKEY` | Auth key Tailscale (Keys → Generate auth key: Reusable ON, expiry 90 ngày, Tags để trống, mô tả `github-ci`). Key chỉ hiện 1 lần lúc tạo — copy ngay vào secret. |

Chưa có secrets nào thì workflow fail ở bước SSH — tạo đủ secrets rồi push lại
(commit trống cũng được: `git commit --allow-empty -m "trigger deploy"`).

## Pipeline (Airflow — scheduler duy nhất, không dùng cron)

- **DAG**: `jobs_daily`, schedule `0 0 * * *` (00:00 UTC = 07:00 ICT)
- **UI**: http://100.80.131.68:8080 (admin/admin — đổi sau lần đầu)
- **Trigger tay**: Airflow UI → `jobs_daily` → Trigger DAG
- **Log**: Airflow UI → DAG → task `run_itviec` / `run_topcv` → Logs

### Run Manually (debug, không schedule)
```bash
cd /mnt/kaggle_data/kaggle_pipeline
source .venv/bin/activate
python -m pipeline run itviec --load-db
python -m pipeline run topcv --max-pages 5 --no-kaggle
```

### Dashboard
```bash
cd /mnt/kaggle_data/kaggle_pipeline
source .venv/bin/activate
streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```

Access at: http://100.80.131.68:8501

## Kaggle Setup (push dataset)

### 1. Lấy API key (làm tay — 2 phút)
1. Mở https://www.kaggle.com/settings/api → **Create New Token** → tải `kaggle.json`
   (chứa `username` + `key`).
2. Ghi nhớ `username` trong file — owner của mọi dataset PHẢI là user này,
   nếu không push sẽ 403. Hiện tại `ITVIEC_KAGGLE_DATASET=quangcrawler/itviec-jobs`
   còn topcv theo `KAGGLE_USERNAME` (default `docutee`): nếu bạn chỉ sở hữu
   1 account thì sửa dataset còn lại về account đó.

### 2. Preflight local (không push gì cả)
```bash
export KAGGLE_USERNAME=quangcrawler KAGGLE_API_TOKEN=<token KGAT_...>
python -m pipeline check-kaggle
# → SẴN SÀNG PUSH mới đi tiếp; FAIL thì đọc kỹ từng dòng lỗi
```

### 3. Đưa creds lên server (chọn 1 cách)
```bash
# Cách A (khuyên dùng): file env cho compose — KHÔNG commit
cp infra/.env.example infra/.env   # rồi điền KAGGLE_USERNAME, KAGGLE_KEY
cd infra && docker compose up -d

# Cách B: export trước khi up
export KAGGLE_USERNAME=<user> KAGGLE_KEY=<key>
cd infra && docker compose up -d
```
Scheduler đọc `KAGGLE_API_TOKEN` từ env (đã đấu sẵn trong
`infra/docker-compose.yml`, cần `kaggle>=2.0` — token KGAT_... không đi qua
`KAGGLE_KEY` cũ). Cách cũ `~/.kaggle/kaggle.json` trên server
vẫn chạy được nhưng không cần nữa khi đã có env.

### Test push thật
```bash
# Local: chạy 1 source, để push bật (mặc định)
python -m pipeline run topcv --max-pages 2
# Server: Airflow UI → jobs_daily → Trigger, xem log task run_topcv tìm "Kaggle push SUCCESS"
```

## Monitoring

### View Logs
```bash
# Airflow task logs: xem trên UI (khuyên dùng)
# Dashboard log
tail -f /mnt/kaggle_data/logs/streamlit.log

# Manual run logs
tail -f /mnt/kaggle_data/kaggle_pipeline/logs/pipeline_itviec_*.log
```

### Check Processes
```bash
# Check if dashboard is running
ps aux | grep streamlit

# Check infra
cd /mnt/kaggle_data/kaggle_pipeline/infra && docker compose ps
```

## Troubleshooting

### Dashboard not accessible
```bash
# Check if streamlit is running
ps aux | grep streamlit

# Restart dashboard
pkill -f streamlit
cd /mnt/kaggle_data/kaggle_pipeline && source .venv/bin/activate && streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
```

### Scraper not working
```bash
# Check Playwright
cd /mnt/kaggle_data/kaggle_pipeline && source .venv/bin/activate
python -c "from playwright.sync_api import sync_playwright; print('OK')"

# Reinstall if needed
playwright install chromium
```

### DAG not running
```bash
cd /mnt/kaggle_data/kaggle_pipeline/infra
docker compose ps
docker compose logs -f airflow-scheduler
# Trigger tay trên UI để test, check task logs trên UI
```
