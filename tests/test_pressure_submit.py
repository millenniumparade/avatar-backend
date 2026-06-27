from __future__ import annotations

from scripts.pressure_submit import JobResult, build_job_specs, is_terminal_status, summarize_results


def test_build_job_specs_uses_unique_device_and_request_ids() -> None:
    specs = build_job_specs(total_jobs=3, device_prefix="stress-user", request_prefix="round-a")

    assert [spec.device_id for spec in specs] == [
        "stress-user-001",
        "stress-user-002",
        "stress-user-003",
    ]
    assert [spec.client_request_id for spec in specs] == [
        "round-a-001",
        "round-a-002",
        "round-a-003",
    ]


def test_is_terminal_status() -> None:
    assert is_terminal_status("succeeded") is True
    assert is_terminal_status("failed") is True
    assert is_terminal_status("timeout") is True
    assert is_terminal_status("cancelled") is True
    assert is_terminal_status("queued") is False
    assert is_terminal_status("processing") is False


def test_summarize_results_counts_statuses_and_latency_percentiles() -> None:
    results = [
        JobResult(index=1, device_id="u-1", status="succeeded", job_id="a", result_id="ra", total_seconds=2.0),
        JobResult(index=2, device_id="u-2", status="failed", job_id="b", error_code="E", total_seconds=4.0),
        JobResult(index=3, device_id="u-3", status="timeout", job_id="c", total_seconds=8.0),
    ]

    summary = summarize_results(results, elapsed_seconds=9.5)

    assert summary["total_jobs"] == 3
    assert summary["succeeded"] == 1
    assert summary["failed"] == 1
    assert summary["timeout"] == 1
    assert summary["cancelled"] == 0
    assert summary["unfinished"] == 0
    assert summary["elapsed_seconds"] == 9.5
    assert summary["latency_seconds"]["avg"] == 4.667
    assert summary["latency_seconds"]["p95"] == 8.0
