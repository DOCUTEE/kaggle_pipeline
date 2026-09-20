#!/usr/bin/env bash
# Scheduler CHÍNH của pipeline — chạy hàng ngày bằng cron.
#
# Cài crontab (07:00 giờ VN, server để TZ Asia/Ho_Chi_Minh):
#   0 7 * * * /mnt/kaggle_data/kaggle_pipeline/scripts/cron_daily.sh >> /mnt/kaggle_data/kaggle_pipeline/logs/cron.log 2>&1
#
# Script bù những thứ Airflow từng lo:
#   - retry mỗi source vài lần (mặc định 2) trước khi báo fail
#   - ghi log 1 file/ngày: logs/pipeline_YYYY-MM-DD.log
#   - flock: lần chạy trước chưa xong thì bỏ qua, không chồng nhau
#   - exit code != 0 khi có source fail (cron/alert đọc được)
#
# Env (lấy từ infra/.env, override được từ ngoài):
#   PIPELINE_SOURCES=itviec,topcv   PIPELINE_RETRIES=2   PIPELINE_RETRY_DELAY=60
#   PIPELINE_LOAD_DB=1              (0 = không nạp Postgres)
#   PIPELINE_KAGGLE=1               (0 = bỏ push Kaggle)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="${LOG_DIR:-$REPO_ROOT/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/pipeline_$(date +%F).log"
LOCK="$LOG_DIR/.pipeline.lock"

log() { echo "[cron $(date '+%F %T')] $*" | tee -a "$LOG"; }

# ── không cho 2 lần chạy chồng nhau ─────────────────────────────────────────
exec 9>"$LOCK"
if ! flock -n 9; then
  log "lần chạy trước chưa xong — bỏ qua lần này"
  exit 0
fi

# ── env: 1 nguồn sự thật là infra/.env (pipeline tự map POSTGRES_* → DB_*) ──
if [ -f "$REPO_ROOT/infra/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/infra/.env"
  set +a
fi

PY="$REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

# ── preflight: data dir phải ghi được ───────────────────────────────────────
# Volume này từng bị container Airflow (uid 50000) ghi trước, nên khi cron chạy
# bằng user host (uid 1000) có thể bị PermissionError. Báo rõ thay vì fail mơ hồ.
DATA_ROOT="${DATA_ROOT:-$REPO_ROOT/data}"
mkdir -p "$DATA_ROOT" 2>/dev/null
if ! ( : > "$DATA_ROOT/.write_test" ) 2>/dev/null; then
  log "LỖI: không ghi được $DATA_ROOT — sửa bằng: chmod -R a+rwX $DATA_ROOT"
  exit 3
fi
rm -f "$DATA_ROOT/.write_test"

# cron không có locale: Python in tiếng Việt/ký tự mũi tên sẽ lỗi UnicodeEncode
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export LANG="${LANG:-C.UTF-8}"

# cron không có .venv/bin trong PATH → console script (kaggle, playwright…) không thấy.
# Code cũng tự tìm cạnh python, nhưng thêm PATH cho chắc.
export PATH="$(dirname "$PY"):$PATH"

SOURCES="${PIPELINE_SOURCES:-itviec,topcv}"
RETRIES="${PIPELINE_RETRIES:-2}"
RETRY_DELAY="${PIPELINE_RETRY_DELAY:-60}"

FLAGS=()
[ "${PIPELINE_LOAD_DB:-1}" = "1" ] && FLAGS+=(--load-db)
[ "${PIPELINE_KAGGLE:-1}" = "0" ] && FLAGS+=(--no-kaggle)

log "BẮT ĐẦU — sources=$SOURCES flags='${FLAGS[*]:-}' python=$PY"
FAILED=0

for src in ${SOURCES//,/ }; do
  attempt=1
  while :; do
    log "[$src] lần $attempt/$RETRIES"
    if "$PY" -m pipeline run "$src" "${FLAGS[@]}" >>"$LOG" 2>&1; then
      log "[$src] OK"
      break
    fi
    if [ "$attempt" -ge "$RETRIES" ]; then
      log "[$src] THẤT BẠI sau $attempt lần (xem log phía trên)"
      FAILED=1
      break
    fi
    attempt=$((attempt + 1))
    sleep "$RETRY_DELAY"
  done
done

if [ "$FAILED" = 0 ]; then
  log "KẾT THÚC — tất cả source OK"
else
  log "KẾT THÚC — CÓ SOURCE LỖI"
fi
exit "$FAILED"
