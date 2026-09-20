# Yêu cầu DevOps — cấp service & thông tin kết nối

> Mục đích: deploy **Vietnam IT Job Market Pipeline** (itviec + topcv) lên server và
> trả lại thông tin kết nối thật để pipeline chạy & được verify end-to-end.
> Mọi thứ cần cấp đều đã có sẵn trong repo (`infra/docker-compose.yml`, `infra/init.sql`) —
> DevOps **không cần viết gì mới**, chủ yếu là chạy compose + cấp credentials.

---

## 1. Kiến trúc & luồng dữ liệu (để hiểu service nào dùng làm gì)

```
cron 07:00 ICT → scripts/cron_daily.sh (scheduler DUY NHẤT — không dùng Airflow)
        │
        ▼  mỗi source 1 lần:  python -m pipeline run <source> --load-db
   scrape ──> raw JSON ──> process ──> processed_jobs.json ──┬─> PostgreSQL ──> Grafana
   (itviec/topcv)                                            ├─> dashboard HTML tĩnh (Plotly)
                                                             └─> Kaggle dataset (JSON)
```

Không còn CSV, không còn web app Streamlit. **PostgreSQL là nguồn dữ liệu phân tích duy nhất.**

---

## 2. Service cần cấp

| # | Service | Version | Port (nội bộ) | Dùng cho | Ghi chú |
|---|---|---|---|---|---|
| 1 | **PostgreSQL** | 15+ | 5432 | Kho dữ liệu phân tích (`itviec_jobs`, `topcv_jobs` + views) | Schema ở `infra/init.sql` — **bắt buộc apply**, gồm cả `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` cho DB đã tồn tại |
| 2 | **Grafana** | latest | 3000 | Dashboard query trực tiếp Postgres | Datasource provisioning ở `infra/grafana/provisioning/datasources/postgres.yml` |
| 3 | **cron** (trên host) | util-linux | — | **Scheduler duy nhất**: `scripts/cron_daily.sh` 07:00 ICT | Cài bằng `deploy/setup_server.sh`. Retry + log + flock + exit code |
| 4 | **Docker + Docker Compose** | v2 | — | Chạy postgres + grafana | User deploy phải nằm trong group `docker` (compose gọi không qua `sudo`) |
| 6 | **Kaggle API** (egress) | CLI `kaggle>=2.0` | — | Push dataset | Token mới dạng `KGAT_...`; `kaggle<2.0` **không dùng được token này** |
| 6 | **Host venv** | Python 3.12 | — | cron + chạy tay `python -m pipeline run ...` | `pip install -r requirements.txt` + `playwright install chromium` (**bắt buộc** cho scraper topcv) |

**Tài nguyên gợi ý (theo server hiện tại):** 8GB RAM / 1TB disk; dữ liệu raw ~2–5MB/source/ngày,
retention 30 ngày (pipeline tự xoá snapshot cũ).

### Đường dẫn trên server (đang dùng, đổi được qua env)

| Biến | Giá trị hiện tại | Ghi chú |
|---|---|---|
| `PROJECT_ROOT` | `/mnt/kaggle_data/kaggle_pipeline` | repo code |
| `DATA_ROOT` | `/mnt/kaggle_data` | raw: `<DATA_ROOT>/itviec`, `<DATA_ROOT>/raw/topcv` |
| `LOG_DIR` | `<PROJECT_ROOT>/logs` | log chạy tay |

---

## 3. Secrets / biến môi trường cần cấp

Toàn bộ đọc từ env (`pipeline/settings.py`, `pipeline/db.py`, `scripts/cron_daily.sh`).
File mẫu: `infra/.env.example` → copy thành `infra/.env`, **không commit**.

> **Scheduler = cron** (`scripts/cron_daily.sh`, cài qua `deploy/setup_server.sh`).
> Không dùng Airflow (đã gỡ khỏi repo 2026-09-20).
>
> **1 nguồn sự thật duy nhất:** `infra/.env`. Postgres container, Grafana datasource
> (provisioning interpolate `${POSTGRES_*}`) và cron đều đọc cùng file này —
> đổi password chỉ cần sửa 1 chỗ, không sửa code/compose.

| Biến | Ví dụ | Dùng ở đâu | Bắt buộc |
|---|---|---|---|
| `POSTGRES_DB` | `kaggle_pipeline` | postgres container, Grafana datasource, cron (`DB_NAME`) | ✅ |
| `POSTGRES_USER` | `pipeline` | postgres container, Grafana datasource, cron (`DB_USER`) | ✅ |
| `POSTGRES_PASSWORD` | *(secret)* | postgres container, Grafana datasource, cron (`DB_PASSWORD`) | ✅ |
| `DB_HOST` | `postgres` (trong compose) / IP thật | `pipeline/db.py` | ✅ |
| `DB_PORT` | `5432` | `pipeline/db.py` | ✅ |
| `DB_NAME` | = `POSTGRES_DB` | `pipeline/db.py` | ✅ |
| `DB_USER` | = `POSTGRES_USER` | `pipeline/db.py` | ✅ |
| `DB_PASSWORD` | = `POSTGRES_PASSWORD` | `pipeline/db.py` | ✅ |
| `GF_SECURITY_ADMIN_USER` | `admin` | Grafana login | ✅ |
| `GF_SECURITY_ADMIN_PASSWORD` | *(secret — đổi khỏi `admin`)* | Grafana login | ✅ |
| `KAGGLE_USERNAME` | `quangcrawler` | `kaggle_check.py`, tên dataset mặc định | ⚠️ xem mục 5 |
| `KAGGLE_API_TOKEN` | `KGAT_...` | push dataset | ⚠️ xem mục 5 |
| `ITVIEC_KAGGLE_DATASET` | `quangcrawler/itviec-jobs` | push itviec | ⚠️ owner phải khớp `KAGGLE_USERNAME` |
| `TOPCV_KAGGLE_DATASET` | `docutee/topcv-it-jobs-vietnam` | push topcv | ⚠️ owner phải khớp `KAGGLE_USERNAME` |
| `PIPELINE_SOURCES` | `itviec,topcv` | DAG sinh task theo source | ✅ |
| `PIPELINE_LOAD_DB` | `1` | DAG bật `--load-db` | ✅ |
| `PIPELINE_PYTHON` | `python` (trong container) | DAG gọi pipeline | ✅ |


**Egress cần mở** (nếu có firewall): `itviec.com`, `www.topcv.vn` (scrape) ·
`kaggle.com` + `storage.googleapis.com` (push dataset) · `pypi.org` (pip) ·
`registry-1.docker.io` (image) · `cdn.plot.ly` + `fonts.googleapis.com` (dashboard HTML —
chỉ cần khi **mở** file HTML; pipeline vẫn chạy nếu chặn).

---

## 4. Thông tin cần gửi lại cho tôi (điền vào đây)

> Gửi qua kênh bảo mật (secret manager / file `.env` đặt trên server `chmod 600`).
> **Không** dán password/token vào chat hay ticket public.

### 4.1 PostgreSQL
```
host            = ................   (hoặc "qua SSH tunnel: ssh -L 5432:... ")
port            = ................
database        = ................
user            = ................
password        = ................   (gửi qua secret manager)
sslmode         = disable | require
init.sql đã apply?        [ ] có   [ ] chưa  → nếu chưa: docker exec -i <pg> psql -U <user> -d <db> < infra/init.sql
bảng đã tồn tại?          [ ] itviec_jobs  [ ] topcv_jobs  [ ] views (v_itviec_stats, v_skill_stats, v_daily_counts)
```

### 4.2 Scheduler (cron) + quyền ghi data
```
crontab đã cài?            [ ] có  [ ] chưa     (output: crontab -l)
entry mong đợi: 0 7 * * * /bin/bash /mnt/kaggle_data/kaggle_pipeline/scripts/cron_daily.sh >> .../logs/cron.log 2>&1
log gần nhất:  ................................................ (logs/pipeline_YYYY-MM-DD.log)
data/ ghi được bởi user chạy cron?   [ ] có  [ ] chưa
   → nếu chưa: sudo chown -R <user>:<user> /mnt/kaggle_data/kaggle_pipeline/data
```

### 4.3 Grafana
```
URL             = ................   (vd http://<host>:3000)
username/password = ..............
datasource Postgres đã provision?     [ ] có  [ ] chưa (tên/uid: ............)
dashboard "ITviec Overview" có data?  [ ] có  [ ] chưa
```

### 4.4 Kaggle (xem mục 5 trước khi cấp)
```
account sở hữu dataset = ................
KAGGLE_API_TOKEN       = KGAT_...........   (qua secret manager)
dataset itviec         = ................   (owner/slug)
dataset topcv          = ................   (owner/slug)
```

### 4.5 Truy cập server (để tôi tự verify)
```
SSH host / user        = ................   (vd docutee@100.80.131.68 hoặc IP Tailscale)
SSH key hay password?  = ................
Có cần VPN/Tailscale?  = ................   (nếu có: mời tôi vào tailnet hoặc mở bastion)
Quyền: user thuộc group docker?  [ ] có  [ ] chưa
Đường dẫn ghi được: PROJECT_ROOT=............  DATA_ROOT=............
```

### 4.6 Môi trường
```
[ ] Đây là production   [ ] staging/dev
Có cần alert khi pipeline fail không? (cron mail / Slack webhook)  [ ] có  [ ] không
Backup Postgres định kỳ?  [ ] có (tần suất: ......)  [ ] không
```

---

## 5. ⚠️ Cần chốt trước: 2 dataset Kaggle thuộc 2 account khác nhau

Cấu hình hiện tại đang trỏ tới **2 owner khác nhau**:

```
KAGGLE_USERNAME        = quangcrawler
ITVIEC_KAGGLE_DATASET  = quangcrawler/itviec-jobs          ← owner: quangcrawler
TOPCV_KAGGLE_DATASET   = docutee/topcv-it-jobs-vietnam     ← owner: docutee  ❌ khác owner
```

Kaggle **chỉ cho phép account sở hữu dataset push version mới** — push sang dataset của
account khác luôn trả 403. Pipeline hiện dùng **1 token duy nhất** cho cả 2 source
(`KAGGLE_API_TOKEN`), nên cần chọn 1 trong các hướng:

| Hướng | Việc cần làm |
|---|---|
| **A. Một account sở hữu cả 2** (khuyến nghị) | Tạo dataset topcv mới dưới account đang dùng (vd `quangcrawler/topcv-it-jobs-vietnam`) rồi set `TOPCV_KAGGLE_DATASET` tương ứng. Hoặc transfer dataset cũ sang account này. |
| **B. Giữ 2 account** | Cần chạy task topcv với token khác (2 secret riêng + sửa DAG truyền token theo task) — **cần code change**, báo tôi biết để làm. |
| **C. Tạm không push Kaggle** | Đặt `--no-kaggle` / không set token; pipeline vẫn chạy đủ scrape → process → Postgres → Grafana. |

Cho tôi biết chọn hướng nào + owner thật, tôi sẽ chốt lại env cho khớp.

---

## 6. Sau khi có thông tin, tôi sẽ verify (acceptance criteria)

```bash
# 0. Preflight Kaggle (không tạo/sửa gì, an toàn)
python -m pipeline check-kaggle
#    mong đợi: "KẾT LUẬN: SẴN SÀNG PUSH"

# 1. Chạy thật 1 source, giới hạn page để nhanh
python -m pipeline run itviec --max-pages 2 --load-db
#    mong đợi: steps=[scrape, process, dashboard, load_db, kaggle_push, cleanup]

# 2. Kiểm tra dữ liệu đã vào Postgres
docker exec -it kaggle_postgres psql -U pipeline -d kaggle_pipeline \
  -c "SELECT COUNT(*) FROM itviec_jobs;" \
  -c "SELECT source, COUNT(*) FROM topcv_jobs GROUP BY source;"

# 3. Scheduler: chạy đúng cái cron sẽ chạy, xem log
/mnt/kaggle_data/kaggle_pipeline/scripts/cron_daily.sh; tail -20 ../logs/pipeline_$(date +%F).log

# 4. Grafana: mở dashboard, xác nhận có data
```

**Điều kiện nghiệm thu:** 6 bước chạy hết không lỗi · row count trong Postgres tăng theo
mỗi lần chạy · DAG `jobs_daily` chạy tự động 07:00 ICT · Grafana hiển thị dữ liệu ·
`check-kaggle` báo sẵn sàng (nếu chọn hướng A).

---

## 7. Lệnh DevOps cần chạy (nếu dùng đúng compose trong repo)

```bash
git clone <repo> /mnt/kaggle_data/kaggle_pipeline   # hoặc rsync từ CI
cd /mnt/kaggle_data/kaggle_pipeline
cp infra/.env.example infra/.env && vi infra/.env    # điền secret thật (chmod 600)

cd infra && docker compose up -d                     # postgres + grafana
docker compose ps                                    # tất cả phải "healthy"/"running"

# apply schema (compose tự chạy init.sql khi volume MỚI; DB cũ thì apply tay)
docker exec -i kaggle_postgres psql -U pipeline -d kaggle_pipeline < init.sql

# host venv — cron chạy bằng venv này nên BẮT BUỘC có
cd .. && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium                # bắt buộc cho scraper topcv
```

**Khuyến nghị thêm cho DevOps:**
- **Pin version image** (`postgres:15-alpine`, `grafana/grafana:11.x`) thay vì `grafana/grafana:latest`
  để deploy lặp lại được.
- `infra/.env` phải `chmod 600` và **không commit** (đã nằm trong `.gitignore`).
- Backup volume `pgdata` — Postgres là nơi duy nhất chứa dữ liệu đã transform
  (raw JSON vẫn còn trên disk nhưng không có index/query).
- Code chỉ deploy qua CI/rsync (`deploy/push_to_server.sh` cũng chạy được tay); data/ và logs/ không bị sync đè.

---

## 8. Phụ lục — biến env đầy đủ mà code đọc

`PROJECT_ROOT`, `DATA_ROOT`, `LOG_DIR`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `KAGGLE_USERNAME`, `KAGGLE_API_TOKEN`, `ITVIEC_KAGGLE_DATASET`,
`TOPCV_KAGGLE_DATASET`, `TOPCV_RAW_SUBDIR`, `PIPELINE_SOURCES`, `PIPELINE_LOAD_DB`,
`PIPELINE_PYTHON`.

Nguồn: `pipeline/settings.py`, `pipeline/db.py`, `dags/jobs_daily.py`, `infra/docker-compose.yml`.
