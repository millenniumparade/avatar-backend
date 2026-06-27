#!/usr/bin/env bash
set -euo pipefail

PATTERN='celery.*app.workers.celery_app.celery_app.*avatar_gpu'
PIDS="$(pgrep -f "${PATTERN}" || true)"

if [ -z "${PIDS}" ]; then
  echo "No avatar_gpu Celery worker is running."
  exit 0
fi

echo "Stopping avatar_gpu Celery worker PIDs:"
echo "${PIDS}"
echo "${PIDS}" | xargs -r kill
sleep 2

REMAINING="$(pgrep -f "${PATTERN}" || true)"
if [ -n "${REMAINING}" ]; then
  echo "Force stopping remaining PIDs:"
  echo "${REMAINING}"
  echo "${REMAINING}" | xargs -r kill -9
fi

echo "avatar_gpu Celery workers stopped."
