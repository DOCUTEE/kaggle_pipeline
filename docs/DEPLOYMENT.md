# Deployment Guide (cron + Grafana)

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
# Từ local: sync code + dựng infra (postgres + grafana) + cài crontab
./deploy/setup_server.sh
```

Chi tiết xem `deploy/setup_server.sh`: sync code tới
`/mnt/kaggle_data/kaggle_pipeline`, xóa crontab legacy, chạy
`infra/docker-compose.yml` (postgres + grafana), cài venv + Chromium và
**cài crontab 07:00** (scheduler chính).

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
2. **deploy** (`needs: [test]`) — rsync code kèm `--delete` (trừ `data/`, `logs/`,
   `.venv`, `infra/.env`, `infra/CREDENTIALS.txt`) → chmod quyền đọc cho container →
   `docker compose up -d` (postgres + grafana) → health check Grafana `:3000` + kiểm tra
   entry cron còn nguyên.

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

## Pipeline (cron — scheduler chính)

- **Crontab**: `0 7 * * *` → `scripts/cron_daily.sh` (07:00 ICT)
- **Log**: `logs/pipeline_YYYY-MM-DD.log` (chi tiết) + `logs/cron.log` (stdout cron)
- **Chạy tay ngay**: `./scripts/cron_daily.sh` (giống hệt cron, có retry + flock)
- **Exit code**: 0 = tất cả source OK, 1 = có source lỗi (alert đọc được)

### Run Manually (debug, không schedule)
```bash
cd /mnt/kaggle_data/kaggle_pipeline
source .venv/bin/activate
python -m pipeline run itviec --load-db
python -m pipeline run topcv --max-pages 5 --no-kaggle
```

### Dashboard (Grafana — query Postgres)

Không còn app Streamlit: dữ liệu phân tích query trực tiếp từ PostgreSQL
(`itviec_jobs`, `topcv_jobs`).

```bash
cd /mnt/kaggle_data/kaggle_pipeline/infra && docker compose up -d
```

Access at: http://100.80.131.68:3000 (admin/admin)

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
# Server: ./scripts/cron_daily.sh, rồi grep log tìm "Kaggle push SUCCESS"
```

## Monitoring

### View Logs
```bash
# Log pipeline (cron ghi ở đây)
tail -f /mnt/kaggle_data/kaggle_pipeline/logs/pipeline_$(date +%F).log
# Infra logs (postgres / grafana)
docker compose -f /mnt/kaggle_data/kaggle_pipeline/infra/docker-compose.yml logs -f grafana

# Manual run logs
tail -f /mnt/kaggle_data/kaggle_pipeline/logs/pipeline_itviec_*.log
```

### Check Processes
```bash
# Check infra
cd /mnt/kaggle_data/kaggle_pipeline/infra && docker compose ps
```

## Troubleshooting

### Grafana trống / không có dữ liệu
```bash
# Kiểm tra postgres healthy + đã nạp dữ liệu chưa
cd /mnt/kaggle_data/kaggle_pipeline/infra && docker compose ps
docker exec -it kaggle_postgres psql -U pipeline -d kaggle_pipeline -c "SELECT COUNT(*) FROM itviec_jobs;"

# Nạp lại dữ liệu từ processed JSON
cd /mnt/kaggle_data/kaggle_pipeline && source .venv/bin/activate
python -m pipeline run itviec --load-db
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
# Chạy tay để test (cùng code path với cron):
/mnt/kaggle_data/kaggle_pipeline/scripts/cron_daily.sh
```
