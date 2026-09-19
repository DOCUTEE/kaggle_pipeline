#!/usr/bin/env bash
# Manual runner — chạy tay 1 source để debug, KHÔNG dùng để schedule.
# Schedule duy nhất là Airflow DAG dags/jobs_daily.py (infra/docker-compose.yml).
#
# Usage:
#   ./scripts/run_pipeline.sh itviec|topcv|all [--load-db] [--no-kaggle] [--max-pages N]
#   ./scripts/run_pipeline.sh itviec --data-dir /mnt/kaggle_data/itviec --load-db
#
# Trigger định kỳ: mở Airflow UI (http://localhost:8080) → DAG jobs_daily → Trigger.
#
# Env:
#   PROJECT_ROOT / DATA_ROOT / LOG_DIR / KAGGLE_USERNAME / DB_* (xem pipeline/settings.py)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] || [ $# -eq 0 ]; then
  echo "Usage: $(basename "$0") itviec|topcv|all [--load-db] [--no-kaggle] [--max-pages N]"
  echo " Run 'python -m pipeline run --help' for full options."
  exit 0
fi
SOURCE="${1:-all}"
shift || true

LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
DATE=$(date +%Y-%m-%d)
mkdir -p "$LOG_DIR"

echo "============================================"
echo " Manual run — source=$SOURCE — $(date '+%Y-%m-%d %H:%M:%S')"
echo " (schedule chính: Airflow DAG jobs_daily)"
echo "============================================"

cd "$PROJECT_ROOT"

# ưu tiên venv của repo, fallback python3 hệ thống
if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  PYTHON="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

# shellcheck disable=SC2086
$PYTHON -m pipeline run "$SOURCE" "$@" 2>&1 | tee -a "$LOG_DIR/pipeline_${SOURCE}_${DATE}.log"

echo "Done — log: $LOG_DIR/pipeline_${SOURCE}_${DATE}.log"
