#!/usr/bin/env bash
set -euo pipefail

GPU_CONCURRENCY="${1:-${WORKER_CONCURRENCY:-1}}"

mkdir -p logs

start_if_missing() {
  local name="$1"
  local pattern="$2"
  local log_file="$3"
  shift 3

  if pgrep -f "${pattern}" >/dev/null; then
    echo "${name} is already running."
    return
  fi

  nohup "$@" > "${log_file}" 2>&1 &
  echo "Started ${name}, pid=$!, log=${log_file}"
}

start_if_missing \
  "api" \
  "uvicorn app.main:app" \
  "logs/api.log" \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

start_if_missing \
  "system-worker" \
  "celery.*app.workers.celery_app.celery_app.*avatar_default" \
  "logs/system-worker.log" \
  env ALGORITHM_MODE=mock .venv/bin/celery -A app.workers.celery_app.celery_app worker \
    --loglevel=info \
    -Q avatar_default \
    --concurrency=1 \
    --prefetch-multiplier=1 \
    --max-tasks-per-child=100

start_if_missing \
  "beat" \
  "celery.*app.workers.celery_app.celery_app beat" \
  "logs/beat.log" \
  .venv/bin/celery -A app.workers.celery_app.celery_app beat --loglevel=info

if pgrep -f "celery.*app.workers.celery_app.celery_app.*avatar_gpu" >/dev/null; then
  echo "avatar_gpu worker is already running."
else
  bash scripts/autodl_start_gpu_worker.sh "${GPU_CONCURRENCY}"
fi
