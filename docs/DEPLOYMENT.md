# Deployment Guide

## Server Info
- **IP**: 100.80.131.68
- **OS**: Ubuntu 24.04 LTS
- **User**: docutee
- **Password**: 12032512

## Directory Structure
```
/mnt/kaggle_data/
├── itviec/           # ITviec scraper
├── topcv/            # TopCV scraper
└── logs/             # Shared logs
```

## SSH Access
```bash
ssh docutee@100.80.131.68
# Password: 12032512
```

## TopCV Pipeline

### Location
`/mnt/kaggle_data/topcv/`

### Run Manually
```bash
cd /mnt/kaggle_data/topcv
source .venv/bin/activate
python pipeline/daily_pipeline.py
```

### Cron Job
```
0 6 * * * /mnt/kaggle_data/topcv/run_daily.sh >> /mnt/kaggle_data/logs/topcv_pipeline.log 2>&1
```

### Dashboard
```bash
cd /mnt/kaggle_data/topcv
source .venv/bin/activate
streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```

Access at: http://100.80.131.68:8501

## Kaggle Setup

### Get API Key
1. Go to https://www.kaggle.com/settings/api
2. Generate New Token
3. Download kaggle.json

### Install on Server
```bash
mkdir -p ~/.kaggle
# Copy your kaggle.json to ~/.kaggle/kaggle.json
chmod 600 ~/.kaggle/kaggle.json
```

### Test
```bash
kaggle datasets list -s test
```

## Monitoring

### View Logs
```bash
# Pipeline logs
tail -f /mnt/kaggle_data/logs/topcv_pipeline.log

# Cron logs
tail -f /mnt/kaggle_data/logs/cron.log
```

### Check Processes
```bash
# Check if dashboard is running
ps aux | grep streamlit

# Check cron jobs
crontab -l
```

## Troubleshooting

### Dashboard not accessible
```bash
# Check if streamlit is running
ps aux | grep streamlit

# Restart dashboard
pkill -f streamlit
cd /mnt/kaggle_data/topcv && source .venv/bin/activate && streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
```

### Scraper not working
```bash
# Check Playwright
cd /mnt/kaggle_data/topcv && source .venv/bin/activate
python -c "from playwright.sync_api import sync_playwright; print('OK')"

# Reinstall if needed
playwright install chromium
```

### Cron not running
```bash
# Check cron service
sudo service cron status

# View cron logs
grep CRON /var/log/syslog
```
