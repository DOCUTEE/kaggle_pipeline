#!/bin/bash
# Deploy TAY lên server (không qua CI) — dùng khi cần đẩy code ngay.
#
#   ./deploy/push_to_server.sh              # rsync code + build image + compose up + health check
#   ./deploy/push_to_server.sh --dry-run    # chỉ xem file nào sẽ đổi/xoá, không làm gì
#   ./deploy/push_to_server.sh --no-build   # bỏ qua bước build image (nhanh hơn)
#
# Khác CI ở chỗ: CI chạy test trước rồi mới rsync; script này KHÔNG chạy test —
# chạy `python -m unittest discover -s tests` trước nếu muốn chắc.
#
# Env override: SERVER_IP, SERVER_USER, SERVER_PASS, REMOTE_DIR
set -euo pipefail

SERVER_IP="${SERVER_IP:-100.80.131.68}"          # IP Tailscale
SERVER_USER="${SERVER_USER:-docutee}"
SERVER_PASS="${SERVER_PASS:-12032512}"           # nên chuyển sang SSH key khi rảnh
REMOTE_DIR="${REMOTE_DIR:-/mnt/kaggle_data/kaggle_pipeline}"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

DRY_RUN=0
BUILD=1
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-build) BUILD=0 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Tham số lạ: $arg"; exit 2 ;;
  esac
done

export SSHPASS="$SERVER_PASS"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 ${SERVER_USER}@${SERVER_IP}"

# --delete: file bị xoá/đổi tên trong repo phải biến mất trên server (nếu không,
# module cũ nằm cạnh package mới từng làm pipeline chết vì import arxiv).
# Các --exclude là những thứ CHỈ có trên server — rsync không xoá path bị exclude.
RSYNC_ARGS=(
  -avz --delete --timeout=120
  # --chmod: file trong repo local có thể là 600 (umask của máy dev), rsync -a sẽ
  # giữ nguyên và container (uid 50000) KHÔNG đọc được → PermissionError khi
  # import. Chuẩn hoá về 644/755 ngay khi truyền.
  --chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r
  -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20"
  --exclude=.git
  --exclude=.venv
  --exclude=__pycache__
  --exclude='*.pyc'
  --exclude=logs/
  --exclude=data/
  --exclude=infra/.env
  --exclude=infra/CREDENTIALS.txt
  --exclude='*.bak'
  --exclude='*.tar.gz'
)

echo "=========================================="
echo " Deploy ${LOCAL_DIR} → ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}"
if [ "$DRY_RUN" = 1 ]; then echo " DRY-RUN (không thay đổi gì)"; else echo " THẬT"; fi
echo "=========================================="

if [ "$DRY_RUN" = 1 ]; then
  echo "--- file sẽ BỊ XOÁ trên server ---"
  sshpass -e rsync "${RSYNC_ARGS[@]}" --dry-run "$LOCAL_DIR/" "${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/" \
    | grep '^deleting' || echo "  (không có)"
  echo "--- hết (bỏ --dry-run để deploy thật) ---"
  exit 0
fi

echo "[1/4] rsync code..."
sshpass -e rsync "${RSYNC_ARGS[@]}" "$LOCAL_DIR/" "${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/"

echo "[2/4] build image Airflow (có Playwright + Chromium)..."
if [ "$BUILD" = 1 ]; then
  $SSH "cd ${REMOTE_DIR}/infra && docker compose build"
else
  echo "  (bỏ qua theo --no-build)"
fi

echo "[3/4] compose up + đồng bộ venv host..."
$SSH "set -e
  cd ${REMOTE_DIR}
  # quyền đọc cho container (uid 50000) — chỉ code, KHÔNG đụng infra/.env
  chmod -R a+rX dags pipeline scripts tests docs deploy infra/grafana 2>/dev/null || true
  chmod a+r infra/*.sql infra/*.yml infra/Dockerfile 2>/dev/null || true
  chmod 600 infra/.env 2>/dev/null || true
  # data/ được ghi bởi 2 uid khác nhau: cron (host, 1000) và Airflow container (50000)
  chmod -R a+rwX data 2>/dev/null || true
  docker compose -f infra/docker-compose.yml up -d
  docker compose -f infra/docker-compose.yml ps
  .venv/bin/pip install -q -r requirements.txt 2>/dev/null || true"

echo "[4/4] health check..."
$SSH "set -a; . ${REMOTE_DIR}/infra/.env 2>/dev/null; set +a
      docker exec kaggle_postgres psql -U \"\${POSTGRES_USER:-pipeline}\" -d \"\${POSTGRES_DB:-kaggle_pipeline}\" -tAc \
        'SELECT 1' >/dev/null 2>&1 && echo '  postgres: OK' || echo '  postgres: FAIL'
      curl -s -o /dev/null -w '  grafana:%{http_code}\n' --max-time 20 http://localhost:3000/api/health
      docker ps --filter name=kaggle_airflow_webserver --format '  airflow (optional): {{.Status}}' | grep . || echo '  airflow (optional): không chạy (bình thường — scheduler là cron)'"

echo ""
echo "Xong. Scheduler chính là cron 07:00 (scripts/cron_daily.sh)."
echo "Chạy pipeline tay trên server:"
echo "  ssh ${SERVER_USER}@${SERVER_IP}"
echo "  cd ${REMOTE_DIR} && set -a && . infra/.env && set +a && .venv/bin/python -m pipeline run topcv --load-db"
