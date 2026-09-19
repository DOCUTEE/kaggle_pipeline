#!/usr/bin/env bash
# Chạy 1 lần thu thập arXiv: metadata -> Postgres, PDF -> MinIO.
# Không đưa vào DAG daily (arxiv schedule=manual trong pipeline/settings.py).
#
# Usage:
#   ./scripts/run_arxiv_once.sh                                  # 100 papers cs.AI
#   ARXIV_QUERY="cat:cs.CL" ARXIV_MAX_RESULTS=50 ./scripts/run_arxiv_once.sh
#   ARXIV_QUERY="all:large language model" ARXIV_MAX_RESULTS=20 ARXIV_DOWNLOAD_PDF=0 ./scripts/run_arxiv_once.sh
#   ./scripts/run_arxiv_once.sh --no-db                          # skip Postgres
#
# Env đọc bởi pipeline:
#   ARXIV_QUERY, ARXIV_MAX_RESULTS, ARXIV_SORT_BY, ARXIV_SORT_ORDER,
#   ARXIV_DOWNLOAD_PDF, ARXIV_PAGE_SIZE,
#   MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET, MINIO_SECURE,
#   DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
#   DATA_ROOT (default <repo>/data, raw arxiv nằm ở $DATA_ROOT/raw/arxiv)
set -euo pipefail

SKIP_DB=0
for arg in "$@"; do
  case "$arg" in
    --no-db) SKIP_DB=1 ;;
    -h|--help)
      echo "Usage: $0 [--no-db]"
      echo "Env: ARXIV_QUERY (default cat:cs.AI), ARXIV_MAX_RESULTS (default 100)"
      exit 0 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export ARXIV_QUERY="${ARXIV_QUERY:-cat:cs.AI}"
export ARXIV_MAX_RESULTS="${ARXIV_MAX_RESULTS:-100}"

LOAD_DB_FLAG=""
if [ "$SKIP_DB" -eq 0 ]; then
  LOAD_DB_FLAG="--load-db"
fi

# shellcheck disable=SC2086
if command -v uv >/dev/null 2>&1; then
  uv run --frozen python -m pipeline run arxiv --no-kaggle $LOAD_DB_FLAG
else
  python -m pipeline run arxiv --no-kaggle $LOAD_DB_FLAG
fi
