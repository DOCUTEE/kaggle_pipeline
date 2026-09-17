#!/bin/bash
# Server Setup Script for TopCV Pipeline
# Deploy to 100.80.131.68

set -e

SERVER_IP="100.80.131.68"
SERVER_USER="root"
REMOTE_DIR="/opt/topcv_pipeline"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=========================================="
echo "Deploying TopCV Pipeline to ${SERVER_IP}"
echo "=========================================="

# 1. Create remote directory
echo "[1/6] Creating remote directory..."
ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${REMOTE_DIR}" || true

# 2. Copy project files
echo "[2/6] Copying project files..."
scp -r "${LOCAL_DIR}/scraper" ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/
scp -r "${LOCAL_DIR}/pipeline" ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/
scp -r "${LOCAL_DIR}/dashboard" ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/
scp -r "${LOCAL_DIR}/data" ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/
scp "${LOCAL_DIR}/requirements.txt" ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/

# 3. Install dependencies
echo "[3/6] Installing Python dependencies..."
ssh ${SERVER_USER}@${SERVER_IP} << 'EOF'
cd /opt/topcv_pipeline

# Install Python 3 and pip
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
playwright install-deps

echo "Dependencies installed!"
EOF

# 4. Setup Kaggle credentials
echo "[4/6] Setting up Kaggle credentials..."
ssh ${SERVER_USER}@${SERVER_IP} << 'EOF'
mkdir -p ~/.kaggle
cat > ~/.kaggle/kaggle.json << 'KAGGLE_EOF'
{
  "username": "docutee",
  "key": "YOUR_KAGGLE_KEY_HERE"
}
KAGGLE_EOF
chmod 600 ~/.kaggle/kaggle.json
echo "Kaggle credentials setup (update key manually)!"
EOF

# 5. Setup cron job
echo "[5/6] Setting up daily cron job..."
ssh ${SERVER_USER}@${SERVER_IP} << 'EOF'
# Create runner script
cat > /opt/topcv_pipeline/run_daily.sh << 'RUNNER_EOF'
#!/bin/bash
cd /opt/topcv_pipeline
source venv/bin/activate
python pipeline/daily_pipeline.py >> /var/log/topcv_pipeline.log 2>&1
RUNNER_EOF
chmod +x /opt/topcv_pipeline/run_daily.sh

# Add cron job (6 AM daily)
(crontab -l 2>/dev/null | grep -v "topcv_pipeline"; echo "0 6 * * * /opt/topcv_pipeline/run_daily.sh") | crontab -

# Create log directory
touch /var/log/topcv_pipeline.log

echo "Cron job setup (6 AM daily)!"
EOF

# 6. Setup Streamlit dashboard
echo "[6/6] Setting up Streamlit dashboard..."
ssh ${SERVER_USER}@${SERVER_IP} << 'EOF'
cd /opt/topcv_pipeline

# Create systemd service for Streamlit
cat > /etc/systemd/system/topcv-dashboard.service << 'SERVICE_EOF'
[Unit]
Description=TopCV Job Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/topcv_pipeline
ExecStart=/opt/topcv_pipeline/venv/bin/streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# Enable and start service
systemctl daemon-reload
systemctl enable topcv-dashboard
systemctl start topcv-dashboard

echo "Dashboard started on port 8501!"
EOF

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo "Dashboard URL: http://${SERVER_IP}:8501"
echo ""
echo "To run first scrape:"
echo "  ssh ${SERVER_USER}@${SERVER_IP}"
echo "  cd ${REMOTE_DIR}"
echo "  source venv/bin/activate"
echo "  python pipeline/daily_pipeline.py"
