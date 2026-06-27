from __future__ import annotations

import json

import pytest

from app.algorithms.faceverse_v4_adapter import validate_faceverse_v4_assets
from app.algorithms.pipeline import generate_cartoon_avatar, preload_models
from app.algorithms.types import PipelineConfig
from app.core.config import settings
from app.core.errors import AvatarError


def test_mock_pipeline_returns_example_human_info(monkeypatch, tmp_path) -> None:
    example = tmp_path / "HumanInfo.json"
    example.write_text(json.dumps({"hair": 22, "shapeKeys": []}), encoding="utf-8")
    monkeypatch.setattr(settings, "mock_algorithm_delay_seconds", 0)
    monkeypatch.setattr(settings, "mock_human_info_path", str(example))

    result = generate_cartoon_avatar(
        input_image_path="ignored.jpg",
        work_dir=str(tmp_path),
        config=PipelineConfig(
            algorithm_version="algo-1",
            asset_library_version="assets-1",
            timeout_seconds=300,
        ),
        models=preload_models(),
    )

    assert result.human_info["hair"] == 22
    assert result.human_info["algorithm_version"] == "algo-1"
    assert result.timing == {"mock_algorithm_seconds": 0.0}


def test_faceverse_v4_pipeline_uses_preloaded_runner(monkeypatch, tmp_path) -> None:
    class FakeFaceVerseRunner:
        def run_image(self, input_image_path: str, *, compute_vertices: bool):
            assert input_image_path == "input.jpg"
            assert compute_vertices is False
            return {
                "device": "cuda",
                "coeff_shape": [1, 621],
                "bbox": [[1, 2, 3, 4]],
                "vertex_count": 200,
                "face_count": 100,
                "timing": {"faceverse_v4_total_seconds": 0.25},
            }

    monkeypatch.setattr(settings, "algorithm_mode", "faceverse_v4")
    monkeypatch.setattr(settings, "faceverse_v4_compute_vertices", False)
    try:
        result = generate_cartoon_avatar(
            input_image_path="input.jpg",
            work_dir=str(tmp_path),
            config=PipelineConfig(
                algorithm_version="algo-faceverse",
                asset_library_version="assets-1",
                timeout_seconds=300,
            ),
            models={"faceverse_v4": FakeFaceVerseRunner()},
        )
    finally:
        monkeypatch.setattr(settings, "algorithm_mode", "mock")

    assert result.human_info["mode"] == "faceverse_v4"
    assert result.human_info["faceverse_v4"]["coeff_shape"] == [1, 621]
    assert result.human_info["faceverse_v4"]["device"] == "cuda"
    assert result.timing == {"faceverse_v4_total_seconds": 0.25}


def test_faceverse_v4_asset_validation_reports_missing_files(tmp_path) -> None:
    (tmp_path / "data").mkdir()

    with pytest.raises(AvatarError) as exc_info:
        validate_faceverse_v4_assets(tmp_path)

    assert "Missing FaceVerse_v4 asset files" in exc_info.value.message
    assert "faceverse_v4_2.npy" in exc_info.value.message
