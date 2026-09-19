#!/bin/bash
# Push code from local to server
# Usage: ./deploy/push_to_server.sh

set -e

SERVER_IP="100.80.131.68"
SERVER_USER="docutee"
SERVER_PASS="12032512"
REMOTE_DIR="/mnt/kaggle_data/topcv"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=========================================="
echo "Pushing code to ${SERVER_IP}"
echo "=========================================="

# Create remote directory if needed
sshpass -p "${SERVER_PASS}" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} "mkdir -p ${REMOTE_DIR}/data/raw/topcv ${REMOTE_DIR}/logs"

# Sync code (excluding data, venv, __pycache__)
sshpass -p "${SERVER_PASS}" rsync -avz --progress -e "ssh -o StrictHostKeyChecking=no" \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='data/raw/topcv/*.csv' \
    --exclude='data/raw/topcv/*.json' \
    "${LOCAL_DIR}/" ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/

echo ""
echo "=========================================="
echo "Code pushed successfully!"
echo "=========================================="
echo ""
echo "Next steps on server:"
echo "  ssh ${SERVER_USER}@${SERVER_IP}"
echo "  cd ${REMOTE_DIR}"
echo "  source .venv/bin/activate"
echo "  python -m pipeline run topcv"
