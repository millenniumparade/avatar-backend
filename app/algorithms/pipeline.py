"""Avatar generation pipeline.

The public contract is stable: input one image, run the configured
reconstruction backend, and return a Unity-consumable HumanInfo JSON payload.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.algorithms.types import PipelineConfig, PipelineResult
from app.core.config import settings
from app.core.errors import AvatarError, ErrorCode


def preload_models() -> dict[str, object]:
    """Load process-scoped model handles for the configured algorithm mode."""

    mode = settings.algorithm_mode.lower()
    if mode == "faceverse_v4":
        from app.algorithms.faceverse_v4_adapter import load_faceverse_v4_runner

        return {"mode": mode, "faceverse_v4": load_faceverse_v4_runner()}
    if mode != "mock":
        raise AvatarError(ErrorCode.MODEL_INFERENCE_FAILED, f"Unsupported ALGORITHM_MODE: {settings.algorithm_mode}")
    return {"mode": "mock"}


def generate_cartoon_avatar(
    input_image_path: str,
    work_dir: str,
    config: PipelineConfig,
    models: dict[str, object] | None = None,
) -> PipelineResult:
    """Run the configured avatar pipeline and return a HumanInfo payload."""

    mode = settings.algorithm_mode.lower()
    if mode == "faceverse_v4":
        return _run_faceverse_v4_pipeline(
            input_image_path=input_image_path,
            work_dir=work_dir,
            config=config,
            models=models,
        )
    if mode != "mock":
        raise AvatarError(ErrorCode.MODEL_INFERENCE_FAILED, f"Unsupported ALGORITHM_MODE: {settings.algorithm_mode}")
    return _run_mock_pipeline(config=config)


def _run_mock_pipeline(*, config: PipelineConfig) -> PipelineResult:
    if settings.mock_algorithm_delay_seconds > 0:
        time.sleep(settings.mock_algorithm_delay_seconds)

    example_path = Path(settings.mock_human_info_path)
    if not example_path.is_absolute():
        example_path = Path.cwd() / example_path

    with example_path.open("r", encoding="utf-8") as input_file:
        human_info = json.load(input_file)

    human_info.setdefault("schema_version", settings.result_schema_version)
    human_info.setdefault("algorithm_version", config.algorithm_version)
    human_info.setdefault("asset_library_version", config.asset_library_version)

    return PipelineResult(
        human_info=human_info,
        preview_image_path=None,
        artifact_paths={},
        timing={"mock_algorithm_seconds": float(settings.mock_algorithm_delay_seconds)},
    )


def _run_faceverse_v4_pipeline(
    *,
    input_image_path: str,
    work_dir: str,
    config: PipelineConfig,
    models: dict[str, object] | None = None,
) -> PipelineResult:
    runner = (models or {}).get("faceverse_v4")
    if runner is None:
        from app.algorithms.faceverse_v4_adapter import load_faceverse_v4_runner

        runner = load_faceverse_v4_runner()

    metadata = runner.run_image(
        input_image_path,
        compute_vertices=settings.faceverse_v4_compute_vertices,
    )
    human_info = {
        "schema_version": settings.result_schema_version,
        "algorithm_version": config.algorithm_version,
        "asset_library_version": config.asset_library_version,
        "mode": "faceverse_v4",
        "faceverse_v4": {
            "device": metadata["device"],
            "coeff_shape": metadata["coeff_shape"],
            "bbox": metadata["bbox"],
            "vertex_count": metadata["vertex_count"],
            "face_count": metadata["face_count"],
        },
    }
    return PipelineResult(
        human_info=human_info,
        preview_image_path=None,
        artifact_paths={},
        timing=metadata["timing"],
    )
