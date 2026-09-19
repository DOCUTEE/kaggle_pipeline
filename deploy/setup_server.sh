#!/bin/bash
# Setup server environment — Airflow-only (không dùng cron).
# Usage: ./deploy/setup_server.sh

set -e

SERVER_IP="100.80.131.68"
SERVER_USER="docutee"
SERVER_PASS="12032512"
REMOTE_DIR="/mnt/kaggle_data/kaggle_pipeline"

echo "=========================================="
echo "Setting up server ${SERVER_IP} (Airflow)"
echo "=========================================="

# 1. Sync code
echo "[1/5] Syncing code..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} \
    "mkdir -p ${REMOTE_DIR} /mnt/kaggle_data/logs"
sshpass -p "${SERVER_PASS}" rsync -avz --progress -e "ssh -o StrictHostKeyChecking=no" \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='logs/' \
    --exclude='data/' \
    "$(cd "$(dirname "$0")/.." && pwd)/" ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/

# 2. Gỡ cron cũ (nếu còn) — pipeline giờ chạy bằng Airflow DAG jobs_daily
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

# 3. Start infra (Postgres + Grafana + Airflow) bằng Docker Compose
echo "[3/5] Starting Docker infra (postgres, grafana, airflow)..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} << 'EOF'
cd /mnt/kaggle_data/kaggle_pipeline/infra
docker compose up -d --build
echo "Waiting for Airflow webserver..."
sleep 20
docker compose ps
EOF

# 4. Host venv (chỉ để chạy tay `python -m pipeline run ...`; pipeline thật chạy trong Airflow container)
echo "[4/5] Preparing host venv..."
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} << 'EOF'
cd /mnt/kaggle_data/kaggle_pipeline
source .venv/bin/activate 2>/dev/null || python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
playwright install chromium 2>/dev/null || true
# Dọn tiến trình Streamlit cũ (dashboard đã bỏ — dữ liệu query qua Postgres/Grafana)
pkill -f '[s]treamlit run dashboard' 2>/dev/null || true
EOF

echo ""
echo "=========================================="
echo "Setup Complete (Airflow + Grafana)!"
echo "=========================================="
echo "Airflow UI: http://${SERVER_IP}:8080 (admin/admin — đổi sau lần đầu)"
echo "DAG: jobs_daily (schedule 00:00 UTC = 07:00 ICT, trigger tay trên UI)"
echo "Grafana:    http://${SERVER_IP}:3000 (admin/admin) — query trực tiếp Postgres"
echo "SSH: ssh ${SERVER_USER}@${SERVER_IP}"
