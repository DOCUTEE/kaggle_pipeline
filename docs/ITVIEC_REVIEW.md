# ITviec Scraper — Senior Data Engineer Review

Ngày: 2026-09-14
Phạm vi: `itviec_scraper.py` (322 dòng) — scraper 1 file, lưu CSV/JSON.

## Tóm tắt (Executive Summary)

Code **chạy được và đúng**, đã thu được 765 jobs, nhưng nó là một **script, không phải pipeline dữ liệu**. Với nhu cầu "thu thập toàn bộ job" một lần thì ổn; với nhu cầu *chạy định kỳ, theo dõi chênh lệch job, scale nhiều nguồn* thì có 10 vấn đề khối cấu trúc dưới đây. Refactor ở phần sau giải quyết toàn bộ bằng kiến trúc plugin + idempotent storage + backoff/retry + batching + schema validation + atomic write.

## Điểm mạnh

1. **AJAX pagination đúng đắn** — gọi `X-Requested-With: XMLHttpRequest` lấy `jobs_html` JSON, tiết kiệm băng thông thay vì render full page.
2. **Có chờ ngẫu nhiên (polite delay)** giữa các page — tôn trọng server.
3. **Deduplication theo `job_key`** — phòng trang trả trùng.
4. **Lưu cả JSON + CSV** — linh hoạt cho phân tích.
5. Thao tác chuỗi/HTML cơ bản sạch, dễ đọc.

---

## ⚠️ 10 vấn đề chính

### 1. Pipeline không idempotent — chạy lại là nhân đôi dữ liệu (Critical)
Mỗi lần chạy ghi `itviec_jobs_<timestamp>.csv` **mới**, không có upsert theo `job_key`. Chạy job hàng ngày 30 ngày sẽ có 30 file chồng lên nhau, không ai biết file nào là "sự thật". Không có state, không track được job mới/bị gỡ/hết hạn.

### 2. Không có schema validation / data contract (Critical)
Dữ liệu là `dict` trần. Không có gì đảm bảo `posted_time` là chuỗi hợp lệ, `tags` không None, `salary` có format ổn định. Khi site đổi class CSS (chuyện rất thường xảy ra), parser âm thầm trả `""` cho mọi field → **sai mà không ai biết**. Cần dataclass/Pydantic + cảnh báo khi tỉ lệ field rỗng tăng đột biến.

### 3. Retry chỉ 1 lần, backoff cố định, bắt Exception rộng (Critical)
`except Exception` nuốt cả lỗi logic lẫn lỗi mạng. Retry 1 lần sau 3s — nếu site đang quá tải (429) thì 3s không đủ. Không phân biệt `AccessDeniedError` (403/401/429 → phải dừng, không retry) với lỗi tạm thời (timeout, 5xx → retry với exponential backoff).

### 4. Mọi thứ chạy tuần tự — 1 page lỗi CPU IDLE cả pipeline (High)
765 jobs / 39 trang chạy tuần tự với sleep 0.5–1.5s/trang → ~60–90s. Khi thêm nhiều nguồn (TopDev, VietnamWorks...) hoặc cần crawl chi tiết từng JD, thời gian nhân lên. Không có concurrency model, không checkpoint — đang giữa trang 37 mà crash là mất cả.

### 5. Parser gắn chặt với CSS class của site (High)
`parse_job_card` phụ thuộc class như `text-rich-grey`, `flex-shrink-0`, `imb-1`, `text-nowrap`. Đây là class của Bootstrap/theme — **đổi theme là hỏng toàn bộ field âm thầm**. Nên ưu tiên selector mang nghĩa ngữ nghĩa (`h3`, `[data-job-key]`, `itag`) + đặt ngưỡng: nếu >X% field rỗng thì fail loudly thay vì xuất file rỗng.

### 6. `get_total_jobs` dùng regex `(\d+)` lấy số "765" từ text (Medium)
`"765 IT jobs in Vietnam"` → regex lấy số đầu tiên — dính chữ "job**s**" thì vẫn ra 765, nhưng nếu trang đổi cấu trúc (ví dụ "Over 1,000 jobs") là sai. Kiểu "1,234" có dấu phẩy cũng không xử lý. Nên đọc từ một nguồn ổn định hơn hoặc tự phát hiện `has_next` từ HTML pagination thay vì đoán qua regex.

### 7. `import shutil` và `import os` chèn giữa file (Low)
`os` import mà không dùng (dead import). `shutil` import trong hàm (`save_results`) — chạy được nhưng khó kiểm soát dependency, xấu cho tooling (pyflakes, mypy).

### 8. Không có cấu hình — hardcode khắp nơi (Medium)
Header User-Agent, timeout, delay, output dir, page size 20, URL... cứng trong code. Muốn đổi delay/UA/output cho môi trường khác → sửa code. Không đọc `requests_kwargs`/env/config, khó chạy trong CI/CD, khó test với URL giả.

### 9. Lưu file thô không có lineage (Medium)
Không ghi `scraped_at` đầy đủ vào mỗi dòng (chỉ ghi trong JSON wrapper), không có nguồn URL, không version schema. Sau này phân tích thời gian (time-series job) thì không biết dòng nào thuộc lần chạy nào.

### 10. Không có tests (Critical cho độ bền)
Parser phụ thuộc HTML — vốn là thứ dễ vỡ nhất — mà không có 1 test nào. Muốn đổi gì là sợ vỡ. Đây là lý do chính khiến "khó scale": không có lưới an toàn.

---

## Bảng đánh giá theo chiều scale

| Chiều scale | Hiện tại | Cần |
|---|---|---|
| Nhiều job hơn (tăng page) | 39 trang tuần tự, crash giữa chừng mất cả | Checkpoint, resume, concurrency có kiểm soát |
| Nhiều nguồn dữ liệu | Không tách được phần nguồn | Plugin interface `Source` cho mỗi site |
| Chạy định kỳ (daily) | 30 file trùng lặp | Upsert theo key + watermark |
| Thay đổi HTML | Field rỗng âm thầm | Schema validation + fail-fast |
| Sản phẩm hóa (dbt/SQL) | CSV phẳng | Parquet + lakehouse layout |
| Giám sát | print ra console | Structured logging + metrics |

---

## Đề xuất kiến trúc (đã triển khai ở mục Refactor)

```
itviec/
├── __init__.py
├── models.py        # Pydantic/Dataclass schema - data contract
├── client.py        # HTTP client + retry/backoff + rate-limit
├── parser.py        # Tách parser khỏi fetch (selector-driven)
├── storage.py       # Idempotent upsert, atomic write, CSV/JSON
└── runner.py        # Orchestrate: fetch → parse → validate → store
cli.py               # Typer CLI entry
tests/
└── test_parser.py   # Unit test parser trên HTML mẫu (fixtures)
```

**Yêu cầu tối thiểu để scale:**
1. Data contract (Pydantic) + validation với fail-fast nếu field rỗng vượt ngưỡng.
2. Upsert theo `job_key` — job đã có thì update, mới thì insert (idempotent).
3. Retry với exponential backoff + jitter, phân biệt lỗi vĩnh viễn vs tạm thời.
4. Concurrency có kiểm soát (ThreadPoolExecutor giới hạn) cho các page.
5. Cấu hình qua env/CLI thay vì hardcode.
6. Unit test cho parser + client + storage.
7. Payload batching và atomic write.