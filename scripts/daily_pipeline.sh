#!/usr/bin/env bash
# Daily pipeline: Scrape → Process → Dashboard → Kaggle Push
# Runs via cron at 7:00 AM daily
# Output: /mnt/kaggle_data/itviec/

set -euo pipefail

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PROJECT_ROOT="/home/docutee/kaggle_pipeline"
DATA_DIR="/mnt/kaggle_data/itviec"
LOG_DIR="/mnt/kaggle_data/logs"
PYTHON="python3"
DATE=$(date +%Y-%m-%d)
RUN_ID=$(date +%Y-%m-%d_%H%M%S)

# ─── SETUP ────────────────────────────────────────────────────────────────────
mkdir -p "$DATA_DIR" "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/pipeline_${DATE}.log") 2>&1

echo "============================================"
echo " ITviec Daily Pipeline — $RUN_ID"
echo "============================================"

cd "$PROJECT_ROOT"

# ─── STEP 1: SCRAPE ──────────────────────────────────────────────────────────
echo ""
echo "[$(date +%H:%M:%S)] Step 1: Scraping itviec.com..."
$PYTHON -m itviec \
    --output "$DATA_DIR" \
    --workers 4 \
    --timeout 30 \
    --parquet \
    2>&1

SCRAPE_EXIT=$?
if [ $SCRAPE_EXIT -ne 0 ]; then
    echo "[ERROR] Scraper failed with exit code $SCRAPE_EXIT"
    exit 1
fi

# ─── STEP 2: PROCESS ─────────────────────────────────────────────────────────
echo ""
echo "[$(date +%H:%M:%S)] Step 2: Processing data..."

# Copy process script and run
cp "$PROJECT_ROOT/dashboard/process_data.py" "$DATA_DIR/"
cd "$DATA_DIR"
$PYTHON process_data.py "$DATA_DIR" 2>&1

# ─── STEP 3: DASHBOARD ───────────────────────────────────────────────────────
echo ""
echo "[$(date +%H:%M:%S)] Step 3: Building dashboard..."

# Copy dashboard builder and run
cp "$PROJECT_ROOT/dashboard/build_dashboard.py" "$DATA_DIR/"
cd "$DATA_DIR"
$PYTHON build_dashboard.py "$DATA_DIR" 2>&1

# ─── STEP 4: KAGGLE PUSH ─────────────────────────────────────────────────────
echo ""
echo "[$(date +%H:%M:%S)] Step 4: Pushing to Kaggle..."

KAGGLE_DATASET="quangcrawler/itviec-jobs"
KAGGLE_DIR="$DATA_DIR/kaggle_upload"

mkdir -p "$KAGGLE_DIR"

# Prepare dataset files
cp "$DATA_DIR/itviec_jobs_latest.csv" "$KAGGLE_DIR/itviec_jobs.csv"
cp "$DATA_DIR/itviec_jobs_latest.json" "$KAGGLE_DIR/itviec_jobs.json"
cp "$DATA_DIR/processed_jobs.csv" "$KAGGLE_DIR/processed_jobs.csv" 2>/dev/null || true

# Create/update metadata
cat > "$KAGGLE_DIR/dataset-metadata.json" << 'METAEOF'
{
  "title": "ITviec Vietnam IT Job Listings",
  "id": "quangcrawler/itviec-jobs",
  "licenses": [
    {
      "name": "CC0-1.0"
    }
  ]
}
METAEOF

# Push to Kaggle
KAGGLE_BIN="$HOME/.local/bin/kaggle"
export KAGGLE_API_TOKEN=$(python3 -c "import json; print(json.load(open('$HOME/.kaggle/kaggle.json'))['key'])")
export KAGGLE_USERNAME=$(python3 -c "import json; print(json.load(open('$HOME/.kaggle/kaggle.json'))['username'])")

if [ -x "$KAGGLE_BIN" ] || command -v kaggle &> /dev/null; then
    KG="${KAGGLE_BIN:-kaggle}"
    cd "$KAGGLE_DIR"
    $KG datasets create -p . --dir-mode zip 2>&1 || \
    $KG datasets version -m "Daily update $DATE" -p . --dir-mode zip 2>&1
    echo "[OK] Kaggle dataset updated"
else
    echo "[WARN] kaggle CLI not found, skipping push"
    echo "Install: pip3 install --user --break-system-packages kaggle"
fi

# ─── STEP 5: CLEANUP OLD DATA (keep last 30 days) ───────────────────────────
echo ""
echo "[$(date +%H:%M:%S)] Step 5: Cleaning old files..."
find "$DATA_DIR" -name "itviec_jobs_*.csv" -mtime +30 -delete 2>/dev/null || true
find "$DATA_DIR" -name "itviec_jobs_*.json" -mtime +30 -delete 2>/dev/null || true
find "$DATA_DIR" -name "itviec_jobs_*.parquet" -mtime +30 -delete 2>/dev/null || true
find "$LOG_DIR" -name "pipeline_*.log" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "============================================"
echo " Pipeline complete — $(date +%H:%M:%S)"
echo " Data: $DATA_DIR"
echo " Log:  $LOG_DIR/pipeline_${DATE}.log"
echo "============================================"
