from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


TERMINAL_STATUSES = {"succeeded", "failed", "timeout", "cancelled"}
ERROR_STATUSES = {"submit_error", "poll_error", "client_timeout"}


@dataclass(frozen=True)
class JobSpec:
    index: int
    device_id: str
    client_request_id: str


@dataclass
class JobResult:
    index: int
    device_id: str
    status: str
    client_request_id: str | None = None
    job_id: str | None = None
    result_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    submit_seconds: float | None = None
    total_seconds: float | None = None
    started_at: float = field(default=0.0, repr=False, compare=False)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "device_id": self.device_id,
            "client_request_id": self.client_request_id,
            "job_id": self.job_id,
            "result_id": self.result_id,
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "http_status": self.http_status,
            "submit_seconds": self.submit_seconds,
            "total_seconds": self.total_seconds,
        }


def build_job_specs(*, total_jobs: int, device_prefix: str, request_prefix: str) -> list[JobSpec]:
    if total_jobs < 1:
        raise ValueError("total_jobs must be >= 1")
    width = max(3, len(str(total_jobs)))
    return [
        JobSpec(
            index=index,
            device_id=f"{device_prefix}-{index:0{width}d}",
            client_request_id=f"{request_prefix}-{index:0{width}d}",
        )
        for index in range(1, total_jobs + 1)
    ]


def is_terminal_status(status: str) -> bool:
    return status in TERMINAL_STATUSES


def summarize_results(results: list[JobResult], *, elapsed_seconds: float) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1

    latencies = sorted(result.total_seconds for result in results if result.total_seconds is not None)
    unfinished = sum(
        1 for result in results if result.status not in TERMINAL_STATUSES and result.status not in ERROR_STATUSES
    )

    return {
        "total_jobs": len(results),
        "succeeded": status_counts.get("succeeded", 0),
        "failed": status_counts.get("failed", 0),
        "timeout": status_counts.get("timeout", 0),
        "cancelled": status_counts.get("cancelled", 0),
        "errors": sum(status_counts.get(status, 0) for status in ERROR_STATUSES),
        "unfinished": unfinished,
        "status_counts": status_counts,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "latency_seconds": _latency_summary(latencies),
    }


async def run_pressure_test(
    *,
    base_url: str,
    image_path: Path,
    total_jobs: int,
    submit_concurrency: int,
    device_prefix: str,
    request_prefix: str,
    poll_interval_seconds: float,
    poll_timeout_seconds: float,
    request_timeout_seconds: float,
    content_type: str,
    fetch_results: bool,
) -> dict[str, Any]:
    image_bytes = image_path.read_bytes()
    specs = build_job_specs(total_jobs=total_jobs, device_prefix=device_prefix, request_prefix=request_prefix)
    normalized_base_url = base_url.rstrip("/")
    started_at = time.monotonic()

    timeout = httpx.Timeout(request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        submit_results = await _submit_all(
            client=client,
            base_url=normalized_base_url,
            image_bytes=image_bytes,
            image_name=image_path.name,
            content_type=content_type,
            specs=specs,
            submit_concurrency=submit_concurrency,
        )
        results = await _poll_all(
            client=client,
            base_url=normalized_base_url,
            submitted=submit_results,
            poll_interval_seconds=poll_interval_seconds,
            poll_timeout_seconds=poll_timeout_seconds,
            fetch_results=fetch_results,
        )

    elapsed = time.monotonic() - started_at
    return {
        "summary": summarize_results(results, elapsed_seconds=elapsed),
        "jobs": [result.to_public_dict() for result in sorted(results, key=lambda item: item.index)],
    }


async def _submit_all(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    image_bytes: bytes,
    image_name: str,
    content_type: str,
    specs: list[JobSpec],
    submit_concurrency: int,
) -> list[JobResult]:
    semaphore = asyncio.Semaphore(max(submit_concurrency, 1))

    async def submit_one(spec: JobSpec) -> JobResult:
        async with semaphore:
            return await _submit_one_job(
                client=client,
                base_url=base_url,
                image_bytes=image_bytes,
                image_name=image_name,
                content_type=content_type,
                spec=spec,
            )

    return list(await asyncio.gather(*(submit_one(spec) for spec in specs)))


async def _submit_one_job(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    image_bytes: bytes,
    image_name: str,
    content_type: str,
    spec: JobSpec,
) -> JobResult:
    started_at = time.monotonic()
    files = {"image": (image_name, image_bytes, content_type)}
    data = {"client_request_id": spec.client_request_id}
    headers = {"X-Device-Id": spec.device_id}

    try:
        response = await client.post(f"{base_url}/api/v1/avatar/jobs", headers=headers, data=data, files=files)
        submit_seconds = round(time.monotonic() - started_at, 3)
        if response.status_code >= 400:
            return JobResult(
                index=spec.index,
                device_id=spec.device_id,
                client_request_id=spec.client_request_id,
                status="submit_error",
                http_status=response.status_code,
                error_message=response.text[:500],
                submit_seconds=submit_seconds,
                total_seconds=submit_seconds,
                started_at=started_at,
            )

        payload = response.json()
        return JobResult(
            index=spec.index,
            device_id=spec.device_id,
            client_request_id=spec.client_request_id,
            status=str(payload.get("status") or "queued"),
            job_id=payload.get("job_id"),
            http_status=response.status_code,
            submit_seconds=submit_seconds,
            started_at=started_at,
        )
    except Exception as exc:
        elapsed = round(time.monotonic() - started_at, 3)
        return JobResult(
            index=spec.index,
            device_id=spec.device_id,
            client_request_id=spec.client_request_id,
            status="submit_error",
            error_message=str(exc),
            submit_seconds=elapsed,
            total_seconds=elapsed,
            started_at=started_at,
        )


async def _poll_all(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    submitted: list[JobResult],
    poll_interval_seconds: float,
    poll_timeout_seconds: float,
    fetch_results: bool,
) -> list[JobResult]:
    async def poll_one(result: JobResult) -> JobResult:
        if not result.job_id or result.status in ERROR_STATUSES:
            return result
        return await _poll_one_job(
            client=client,
            base_url=base_url,
            result=result,
            poll_interval_seconds=poll_interval_seconds,
            poll_timeout_seconds=poll_timeout_seconds,
            fetch_results=fetch_results,
        )

    return list(await asyncio.gather(*(poll_one(result) for result in submitted)))


async def _poll_one_job(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    result: JobResult,
    poll_interval_seconds: float,
    poll_timeout_seconds: float,
    fetch_results: bool,
) -> JobResult:
    deadline = time.monotonic() + poll_timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = await client.get(f"{base_url}/api/v1/avatar/jobs/{result.job_id}")
            result.http_status = response.status_code
            if response.status_code >= 400:
                result.status = "poll_error"
                result.error_message = response.text[:500]
                result.total_seconds = round(time.monotonic() - result.started_at, 3)
                return result

            payload = response.json()
            result.status = str(payload.get("status") or result.status)
            result.result_id = payload.get("result_id")
            result.error_code = payload.get("error_code")
            result.error_message = payload.get("message")
            if is_terminal_status(result.status):
                result.total_seconds = round(time.monotonic() - result.started_at, 3)
                if fetch_results and result.result_id:
                    await client.get(f"{base_url}/api/v1/avatar/results/{result.result_id}")
                return result
        except Exception as exc:
            result.status = "poll_error"
            result.error_message = str(exc)
            result.total_seconds = round(time.monotonic() - result.started_at, 3)
            return result

        await asyncio.sleep(poll_interval_seconds)

    result.status = "client_timeout"
    result.error_message = f"Polling exceeded {poll_timeout_seconds} seconds."
    result.total_seconds = round(time.monotonic() - result.started_at, 3)
    return result


def _latency_summary(latencies: list[float]) -> dict[str, float | None]:
    if not latencies:
        return {"min": None, "avg": None, "p50": None, "p95": None, "max": None}
    return {
        "min": round(latencies[0], 3),
        "avg": round(sum(latencies) / len(latencies), 3),
        "p50": _percentile(latencies, 50),
        "p95": _percentile(latencies, 95),
        "max": round(latencies[-1], 3),
    }


def _percentile(sorted_values: list[float], percentile: int) -> float:
    index = max(0, math.ceil((percentile / 100) * len(sorted_values)) - 1)
    return round(sorted_values[index], 3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit avatar jobs and wait for terminal results.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--image", default="FaceVerse_v4/example/input/test.jpg")
    parser.add_argument("--jobs", type=int, required=True)
    parser.add_argument("--submit-concurrency", type=int, default=8)
    parser.add_argument("--device-prefix", default="stress-user")
    parser.add_argument("--request-prefix", default=f"stress-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--poll-timeout", type=float, default=900.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--content-type", default="image/jpeg")
    parser.add_argument("--fetch-results", action="store_true")
    parser.add_argument("--json-output")
    parser.add_argument("--exit-nonzero-on-failure", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = Path(args.image)
    if not image_path.exists():
        raise SystemExit(f"Image file does not exist: {image_path}")

    payload = asyncio.run(
        run_pressure_test(
            base_url=args.base_url,
            image_path=image_path,
            total_jobs=args.jobs,
            submit_concurrency=args.submit_concurrency,
            device_prefix=args.device_prefix,
            request_prefix=args.request_prefix,
            poll_interval_seconds=args.poll_interval,
            poll_timeout_seconds=args.poll_timeout,
            request_timeout_seconds=args.request_timeout,
            content_type=args.content_type,
            fetch_results=args.fetch_results,
        )
    )

    output = json.dumps(payload, ensure_ascii=False, indent=2)
    print(output)
    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")

    summary = payload["summary"]
    if args.exit_nonzero_on_failure and summary["succeeded"] != summary["total_jobs"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
