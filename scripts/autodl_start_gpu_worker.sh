#!/usr/bin/env bash
set -euo pipefail

CONCURRENCY="${1:-${WORKER_CONCURRENCY:-1}}"
LOG_FILE="${2:-logs/gpu-worker-c${CONCURRENCY}.log}"

mkdir -p logs

nohup .venv/bin/celery -A app.workers.celery_app.celery_app worker \
  --loglevel=info \
  -Q avatar_gpu \
  --concurrency="${CONCURRENCY}" \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=20 \
  > "${LOG_FILE}" 2>&1 &

echo "Started avatar_gpu worker with concurrency=${CONCURRENCY}, pid=$!, log=${LOG_FILE}"
