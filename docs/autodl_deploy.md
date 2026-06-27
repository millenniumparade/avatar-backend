# AutoDL GPU Deployment

This guide targets an AutoDL instance with:

- GPU: RTX 4090 24GB
- CPU: 16 cores
- RAM: 120GB
- Data disk: 50GB
- Base environment: PyTorch 2.5.1, Python 3.12, Ubuntu 22.04, CUDA 12.4

## Deployment Shape

Only the `avatar_gpu` Celery worker needs CUDA. The API, system worker, beat,
PostgreSQL, Redis, and MinIO run on CPU containers.

```text
api              -> FastAPI HTTP service
worker           -> GPU Celery worker, FaceVerse_v4
system-worker    -> outbox dispatch and stale-job recovery
watchdog         -> Celery beat scheduler
postgres         -> job/result/outbox source of truth
redis            -> admission state and Celery broker
minio            -> uploaded images and generated JSON/artifacts
```

## Files Added for AutoDL

- `Dockerfile.gpu`: GPU worker image based on a PyTorch CUDA image.
- `requirements-gpu.txt`: backend dependencies plus FaceVerse_v4 dependencies, excluding torch/torchvision.
- `docker-compose.autodl.yml`: single-machine AutoDL deployment.
- `.env.autodl.example`: deployment environment template.
- `scripts/check_gpu_env.py`: verifies PyTorch sees CUDA.
- `scripts/run_faceverse_v4_smoke.py`: runs one FaceVerse_v4 image through the adapter.

## Important Dependency Boundary

`requirements.txt` is for normal backend services and intentionally does not
include torch, torchvision, or mediapipe. `requirements-gpu.txt` is for the GPU
worker.

The AutoDL image already provides PyTorch 2.5.1 with CUDA 12.4. Installing plain
`torch==2.5.1` from PyPI can replace it with a CPU-only wheel, so
`requirements-gpu.txt` does not install torch or torchvision.

## Step 1: Prepare the Instance

Clone or upload this repo into the AutoDL data disk, then verify the GPU:

```bash
nvidia-smi
python scripts/check_gpu_env.py --require-cuda
```

Expected checks:

- GPU name should include RTX 4090.
- `cuda_available` should be `true`.
- total memory should be close to 24564 MB.

## Step 2: Prepare Environment File

```bash
cp .env.autodl.example .env.autodl
```

Edit `.env.autodl` and change at least:

```text
POSTGRES_PASSWORD
DATABASE_URL
MINIO_ROOT_PASSWORD
S3_SECRET_ACCESS_KEY
WORKER_CONCURRENCY
```

Start with:

```text
WORKER_CONCURRENCY=1
ALGORITHM_MODE=faceverse_v4
FACEVERSE_V4_ALLOW_CPU_FALLBACK=false
FACEVERSE_V4_COMPUTE_VERTICES=true
```

## Step 3: Build and Start

If Docker and NVIDIA Container Toolkit are available:

```bash
docker compose -f docker-compose.autodl.yml --env-file .env.autodl build
docker compose -f docker-compose.autodl.yml --env-file .env.autodl up -d
docker compose -f docker-compose.autodl.yml --env-file .env.autodl ps
```

Check logs:

```bash
docker compose -f docker-compose.autodl.yml --env-file .env.autodl logs -f worker
docker compose -f docker-compose.autodl.yml --env-file .env.autodl logs -f api
```

If the default `GPU_BASE_IMAGE` cannot be pulled, set it in `.env.autodl` to the
AutoDL-provided PyTorch 2.5.1 / Python 3.12 / CUDA 12.4 Docker image name and
rebuild.

## Step 4: Smoke Test FaceVerse_v4 in the GPU Worker Image

```bash
docker compose -f docker-compose.autodl.yml --env-file .env.autodl run --rm worker \
  python scripts/check_gpu_env.py --require-cuda

docker compose -f docker-compose.autodl.yml --env-file .env.autodl run --rm worker \
  python scripts/run_faceverse_v4_smoke.py --image FaceVerse_v4/example/input/test.jpg
```

Do not pass `--allow-cpu-fallback` on AutoDL. If CUDA is unavailable, fail fast.

## Step 5: Submit One API Job

```bash
curl -X POST \
  -H "X-Device-Id: autodl-user-1" \
  -F "image=@FaceVerse_v4/example/input/test.jpg" \
  http://127.0.0.1:8000/api/v1/avatar/jobs
```

Poll:

```bash
curl http://127.0.0.1:8000/api/v1/avatar/jobs/<job_id>
```

When the job succeeds, fetch:

```bash
curl http://127.0.0.1:8000/api/v1/avatar/results/<result_id>
```

The JSON should include:

```json
{
  "human_info": {
    "mode": "faceverse_v4",
    "faceverse_v4": {
      "device": "cuda",
      "coeff_shape": [1, 621]
    }
  }
}
```

## Step 6: Start Pressure Testing

Increase only the GPU worker concurrency first:

```text
WORKER_CONCURRENCY=1
WORKER_CONCURRENCY=2
WORKER_CONCURRENCY=3
...
```

After each change:

```bash
docker compose -f docker-compose.autodl.yml --env-file .env.autodl up -d --build worker
```

Watch:

```bash
nvidia-smi
docker compose -f docker-compose.autodl.yml --env-file .env.autodl logs -f worker
```

Stop increasing concurrency when you see CUDA OOM, timeout, or throughput stops
improving.

## If Docker Is Not Available on AutoDL

Use the AutoDL PyTorch environment directly for the GPU worker, and run
PostgreSQL/Redis/MinIO however AutoDL allows. The key rules remain:

- Do not reinstall CPU torch over the CUDA torch.
- Install `requirements-gpu.txt` only after confirming torch CUDA is available.
- Run the worker with `ALGORITHM_MODE=faceverse_v4` and
  `FACEVERSE_V4_ALLOW_CPU_FALLBACK=false`.
