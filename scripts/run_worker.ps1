celery -A app.workers.celery_app.celery_app worker --loglevel=info -Q avatar_gpu --concurrency=4 --prefetch-multiplier=1 --max-tasks-per-child=20
