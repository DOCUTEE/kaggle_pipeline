# arXiv one-shot pipeline — PDF → MinIO, metadata → Postgres

Chạy **1 lần** theo yêu cầu (không đưa vào DAG daily). Đi đúng pattern 6 bước
chung trong `docs/PIPELINE_PATTERN.md`, chỉ khác: file PDF đẩy lên MinIO (S3),
metadata vào bảng `arxiv_papers`.

## Giả định

"Thu thập thêm báo" = thu **paper arXiv** (trang bạn vừa check, mỗi paper có PDF).
Query mặc định `cat:cs.AI`. Đổi query qua env `ARXIV_QUERY` là thu chủ đề khác.
Nếu bạn muốn báo điện tử VN (VnExpress/Tuổi Trẻ/...) thì reuse đúng khung này:
thay `pipeline/sources/arxiv.py` bằng adapter mới, giữ nguyên MinIO + Postgres.

## Chạy 1 lần

```bash
# 1. Infra (lần đầu): Postgres + MinIO
cd infra && docker compose up -d postgres minio
# MinIO console: http://localhost:9001 (minioadmin/minioadmin)
# Bucket tự tạo: arxiv-pdfs (code tự tạo nếu chưa có)

# 2. Deps (uv)
uv sync

# 3. Chạy 1 lần (100 papers cs.AI, có tải PDF, có nạp Postgres, skip Kaggle)
./scripts/run_arxiv_once.sh   # tự dùng uv nếu có, fallback python

# Biến thể:
ARXIV_QUERY="cat:cs.CL" ARXIV_MAX_RESULTS=50 ./scripts/run_arxiv_once.sh
ARXIV_QUERY="all:large language model" ARXIV_MAX_RESULTS=20 ARXIV_DOWNLOAD_PDF=0 ./scripts/run_arxiv_once.sh
./scripts/run_arxiv_once.sh --no-db          # bỏ qua Postgres
ARXIV_MAX_RESULTS=5 uv run python -m pipeline run arxiv --no-kaggle   # test nhanh, không DB
```

## Luồng dữ liệu

```
arXiv API (Atom XML, delay 3s/request)
  → data/raw/arxiv/arxiv_*.json + .csv + arxiv_latest.*
  → data/raw/arxiv/pdfs/<arxiv_id>.pdf   (skip nếu đã có = idempotent)
  → MinIO bucket arxiv-pdfs, key arxiv/<arxiv_id>.pdf
      + reachable    → pdf_location = s3://arxiv-pdfs/arxiv/<id>.pdf
      + chưa chạy    → fallback file://<local>, metadata vẫn lưu đủ
  → process → data/raw/arxiv/dashboard/processed_arxiv.csv
  → load_db → bảng arxiv_papers (upsert theo arxiv_id)
  → dashboard → arxiv_dashboard.html
```

## Env

| Env | Default | Ý nghĩa |
|---|---|---|
| `ARXIV_QUERY` | `cat:cs.AI` | Ngôn ngữ query arXiv API (`cat:cs.CL`, `all:...`, `au:...`) |
| `ARXIV_MAX_RESULTS` | `100` | Tổng paper tối đa / lần chạy |
| `ARXIV_SORT_BY` | `submittedDate` | `submittedDate` \| `lastUpdatedDate` \| `relevance` |
| `ARXIV_SORT_ORDER` | `descending` | `descending` \| `ascending` |
| `ARXIV_DOWNLOAD_PDF` | `1` | `0` = chỉ metadata |
| `ARXIV_PAGE_SIZE` | `100` | Paper mỗi request API |
| `MINIO_ENDPOINT` | `localhost:9000` | Host MinIO (không scheme) |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | `minioadmin` | Key MinIO |
| `MINIO_BUCKET` | `arxiv-pdfs` | Bucket chứa PDF |
| `MINIO_SECURE` | `0` | `1` = https |
| `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD` | `localhost/5432/kaggle_pipeline/pipeline/...` | Postgres |

`--max-pages N` của CLI = `N * ARXIV_PAGE_SIZE` papers (vd `--max-pages 1` ≈ 100 papers).

## Schema `arxiv_papers`

`arxiv_id UNIQUE, title, authors ("; "-join), abstract, categories (";"-join),
primary_category, published, updated, pdf_url, pdf_local, minio_key,
pdf_location (s3://... hoặc file://...), comment, journal_ref, doi,
scrape_date, query, loaded_at`. Xem `infra/init.sql`.

DB cũ chưa có bảng → chạy lại `init.sql` hoặc:
`psql $DB -f infra/init.sql` (CREATE IF NOT EXISTS, an toàn).

## File đã thêm/sửa

- Mới: `pipeline/sources/arxiv.py`, `pipeline/minio_store.py`,
  `scripts/run_arxiv_once.sh`, `docs/ARXIV.md`
- Sửa: `pipeline/sources/__init__.py`, `pipeline/settings.py` (+source `arxiv`),
  `pipeline/runner.py`, `pipeline/build.py` (+`process_arxiv`/`build_arxiv_dashboard`),
  `pipeline/db.py` (+`load_arxiv_csv`), `requirements.txt` (+`boto3`, `feedparser`),
  `infra/docker-compose.yml` (+service `minio`), `infra/init.sql` (+bảng),
  `infra/.env.example` (+MINIO/ARXIV vars)

## Đã test

`ARXIV_MAX_RESULTS=2` trên local: 2 papers, 2 PDF (12MB + 721KB), MinIO chưa
chạy → fallback `file://` đúng thiết kế, process + dashboard + cleanup OK.

## Dashboard World Science Overview

```bash
# Thu mẫu đa ngành (8 ngành x 60, metadata-only, ~1 phút)
uv run python scripts/collect_world_sample.py --per-cat 60

# Build dashboard tĩnh
uv run python -m pipeline.build process arxiv --data-dir data/raw/arxiv
uv run python -m pipeline.build dashboard arxiv --data-dir data/raw/arxiv
# Mở: data/raw/arxiv/dashboard/arxiv_dashboard.html
```

Dashboard gồm: KPI (papers/lĩnh vực/chuyên ngành/keyword nóng), Key Insights tự sinh,
chart lĩnh vực lớn, top 15 chuyên ngành, nhịp xuất bản theo ngày, từ khóa nóng,
tác giả prolific, bảng 50 papers mới nhất link về arXiv.
