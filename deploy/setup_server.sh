#!/bin/bash
# Setup server environment — scheduler là CRON (không dùng Airflow).
# Usage: ./deploy/setup_server.sh
#
# Chạy 1 lần cho server mới. Các lần deploy code bình thường dùng
# ./deploy/push_to_server.sh (nhanh hơn, không cài lại gì).

set -e

SERVER_IP="100.80.131.68"
SERVER_USER="docutee"
SERVER_PASS="12032512"
REMOTE_DIR="/mnt/kaggle_data/kaggle_pipeline"

echo "=========================================="
echo "Setting up server ${SERVER_IP} (cron + grafana)"
echo "=========================================="

# 1. Sync code
echo "[1/5] Syncing code..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} \
    "mkdir -p ${REMOTE_DIR} /mnt/kaggle_data/logs"
sshpass -p "${SERVER_PASS}" rsync -avz --progress --delete \
    --chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r \
    -e "ssh -o StrictHostKeyChecking=no" \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='logs/' \
    --exclude='data/' \
    --exclude='infra/.env' \
    --exclude='infra/CREDENTIALS.txt' \
    "$(cd "$(dirname "$0")/.." && pwd)/" ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/

# 2. Dọn cron legacy (thời pipeline còn nằm ở /mnt/kaggle_data/topcv)
echo "[2/5] Removing legacy cron jobs..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} << 'EOF'
crontab -l 2>/dev/null | grep -v 'kaggle_data/topcv' | grep -v 'kaggle_data/itviec' | crontab - || true
rm -f /mnt/kaggle_data/topcv/run_daily.sh
echo "Legacy cron removed."
EOF

# 2.5. Cài Docker nếu chưa có (cần sudo — dùng SSH password)
echo "[2.5/5] Ensuring Docker is installed..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} "SUDO_PASS='${SERVER_PASS}' bash -s" << 'EOF'
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found — installing via apt..."
  echo "$SUDO_PASS" | sudo -S apt-get update -qq
  echo "$SUDO_PASS" | sudo -S apt-get install -y -qq docker.io docker-compose-plugin
  echo "$SUDO_PASS" | sudo -S systemctl enable --now docker
  echo "$SUDO_PASS" | sudo -S usermod -aG docker "$USER" || true
else
  echo "Docker already installed: $(docker --version)"
fi
EOF

# 3. Infra: postgres + grafana
echo "[3/5] Starting infra (postgres + grafana)..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} << 'EOF'
cd /mnt/kaggle_data/kaggle_pipeline/infra
[ -f .env ] || { echo "THIẾU infra/.env — copy từ .env.example rồi điền secret"; exit 1; }
docker compose up -d
# apply schema (idempotent) cho DB đã tồn tại
set -a; . ./.env; set +a
docker exec -i kaggle_postgres psql -U "${POSTGRES_USER:-pipeline}" -d "${POSTGRES_DB:-kaggle_pipeline}" < init.sql >/dev/null 2>&1 || true
sleep 5
docker compose ps
EOF

# 4. Host venv + Chromium (cron chạy trực tiếp trên host nên cần browser thật)
echo "[4/5] Preparing host venv + chromium..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} << 'EOF'
cd /mnt/kaggle_data/kaggle_pipeline
source .venv/bin/activate 2>/dev/null || python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
playwright install chromium || true
# Dọn tiến trình Streamlit cũ (dashboard đã bỏ — dữ liệu query qua Postgres/Grafana)
pkill -f '[s]treamlit run dashboard' 2>/dev/null || true
EOF

# 5. Cài cron — scheduler chính
echo "[5/5] Installing crontab (07:00 mỗi ngày)..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} << 'EOF'
chmod +x /mnt/kaggle_data/kaggle_pipeline/scripts/cron_daily.sh
LINE="0 7 * * * /mnt/kaggle_data/kaggle_pipeline/scripts/cron_daily.sh >> /mnt/kaggle_data/kaggle_pipeline/logs/cron.log 2>&1"
if crontab -l 2>/dev/null | grep -qF 'scripts/cron_daily.sh'; then
  echo "  cron đã có sẵn"
else
  { crontab -l 2>/dev/null; echo "$LINE"; } | crontab -
  echo "  đã cài: $LINE"
fi
crontab -l | sed 's/^/  /'
EOF

echo ""
echo "=========================================="
echo "Setup Complete (cron + Grafana)"
echo "=========================================="
echo "Scheduler: cron 07:00 hàng ngày (log: ${REMOTE_DIR}/logs/pipeline_YYYY-MM-DD.log)"
echo "Grafana:   http://${SERVER_IP}:3000 (query trực tiếp Postgres)"
echo "SSH: ssh ${SERVER_USER}@${SERVER_IP}"
