# AutoDL FaceVerse_v4 Pressure Test Runbook

This runbook assumes the backend has already been deployed on AutoDL and the
single-job smoke path has succeeded.

## 1. Pull the latest code

```bash
cd ~/autodl-tmp/avatar-backend
git pull
source .venv/bin/activate
chmod +x scripts/autodl_*.sh
```

`git pull` updates the pressure-test scripts. `source .venv/bin/activate`
ensures Python commands use the project environment. `chmod +x` makes the shell
scripts executable on Linux.

## 2. Start or verify runtime services

```bash
bash scripts/autodl_start_runtime.sh 1
```

The argument is the GPU worker concurrency. `1` starts one `avatar_gpu` worker
process. The script also starts the API, system worker, and Celery beat if they
are not already running.

Verify the API:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/docs
```

Expected output:

```text
200
```

## 3. Run a baseline pressure round

```bash
python scripts/pressure_submit.py \
  --base-url http://127.0.0.1:8000 \
  --image FaceVerse_v4/example/input/test.jpg \
  --jobs 2 \
  --submit-concurrency 2 \
  --device-prefix stress-c1 \
  --request-prefix c1-$(date +%Y%m%d%H%M%S) \
  --json-output output/pressure-c1.json
```

`--jobs` is the number of avatar jobs submitted to the API. `--submit-concurrency`
only controls HTTP submission concurrency. The actual GPU execution concurrency
is controlled by the Celery worker's `--concurrency` value.

Every submitted job receives a different `X-Device-Id`, such as
`stress-c1-001`, so the backend's one-active-job-per-user guard does not block
the pressure test.

## 4. Increase GPU worker concurrency

For each round, stop the old GPU worker, start a new one with a higher
concurrency, then submit more jobs than worker processes.

```bash
bash scripts/autodl_stop_gpu_workers.sh
bash scripts/autodl_start_gpu_worker.sh 2
python scripts/pressure_submit.py \
  --base-url http://127.0.0.1:8000 \
  --image FaceVerse_v4/example/input/test.jpg \
  --jobs 4 \
  --submit-concurrency 4 \
  --device-prefix stress-c2 \
  --request-prefix c2-$(date +%Y%m%d%H%M%S) \
  --json-output output/pressure-c2.json
```

Next rounds:

```bash
bash scripts/autodl_stop_gpu_workers.sh
bash scripts/autodl_start_gpu_worker.sh 3
python scripts/pressure_submit.py --base-url http://127.0.0.1:8000 --image FaceVerse_v4/example/input/test.jpg --jobs 6 --submit-concurrency 6 --device-prefix stress-c3 --request-prefix c3-$(date +%Y%m%d%H%M%S) --json-output output/pressure-c3.json

bash scripts/autodl_stop_gpu_workers.sh
bash scripts/autodl_start_gpu_worker.sh 4
python scripts/pressure_submit.py --base-url http://127.0.0.1:8000 --image FaceVerse_v4/example/input/test.jpg --jobs 8 --submit-concurrency 8 --device-prefix stress-c4 --request-prefix c4-$(date +%Y%m%d%H%M%S) --json-output output/pressure-c4.json
```

## 5. Watch GPU and worker logs

In another terminal:

```bash
watch -n 1 nvidia-smi
```

Tail the GPU worker log for the current round:

```bash
tail -f logs/gpu-worker-c2.log
```

Use the matching log file name for each concurrency round.

## 6. How to interpret results

Use the JSON summary fields:

```text
summary.succeeded
summary.failed
summary.timeout
summary.errors
summary.latency_seconds.avg
summary.latency_seconds.p95
```

A concurrency level is stable only if all jobs succeed and the GPU worker log has
no CUDA OOM or worker crash. If higher concurrency increases latency heavily
without improving completed jobs per minute, the previous level is usually the
better operating point.

If you see CUDA OOM, stop GPU workers, restart with one lower concurrency, and
rerun the round.

```bash
bash scripts/autodl_stop_gpu_workers.sh
bash scripts/autodl_start_gpu_worker.sh 2
```
