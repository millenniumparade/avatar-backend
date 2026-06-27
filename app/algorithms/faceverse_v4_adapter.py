"""Adapter for the local FaceVerse_v4 checkout.

The backend only needs to verify that FaceVerse_v4 can consume one uploaded
image and run the reconstruction model. Mesh export stays outside this adapter
for now; the pipeline records timing and shape metadata instead.
"""

from __future__ import annotations

import sys
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.errors import AvatarError, ErrorCode


REQUIRED_FACEVERSE_V4_FILES = (
    "faceverse_v4_2.npy",
    "faceverse_resnet50.pth",
    "face_landmarker.task",
)


class FaceVerseV4Runner:
    """Small runtime wrapper around FaceVerse_v4's model API."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        device_name: str | None = None,
        allow_cpu_fallback: bool | None = None,
    ) -> None:
        self.root = resolve_faceverse_v4_root(root)
        self.data_dir = self.root / "data"
        self.paths = validate_faceverse_v4_assets(self.root)

        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))

        os.environ.setdefault(
            "MPLCONFIGDIR",
            str(Path(tempfile.gettempdir()) / "avatar-backend-matplotlib"),
        )

        try:
            import cv2
            import mediapipe as mp
            import numpy as np
            import torch
            from faceversev4 import FaceVerseRecon
        except ModuleNotFoundError as exc:
            raise AvatarError(
                ErrorCode.MODEL_INFERENCE_FAILED,
                f"Missing FaceVerse_v4 dependency: {exc.name}. Run pip install -r requirements.txt.",
            ) from exc

        self.cv2 = cv2
        self.mp = mp
        self.np = np
        self.torch = torch
        self.device = self._select_device(
            device_name or settings.faceverse_v4_device,
            allow_cpu_fallback=(
                settings.faceverse_v4_allow_cpu_fallback
                if allow_cpu_fallback is None
                else allow_cpu_fallback
            ),
        )

        started = time.perf_counter()
        self.model = FaceVerseRecon(
            str(self.paths["faceverse_v4_2.npy"]),
            str(self.paths["faceverse_resnet50.pth"]),
            self.device,
        )
        self.load_seconds = time.perf_counter() - started
        self.face_tracker = self._build_face_tracker()

    def run_image(
        self,
        input_image_path: str | Path,
        *,
        compute_vertices: bool = True,
    ) -> dict[str, Any]:
        """Run FaceVerse_v4 on one image and return lightweight metadata."""

        image_path = Path(input_image_path)
        if not image_path.exists():
            raise AvatarError(ErrorCode.NOT_FOUND, f"Input image was not found: {image_path}")

        started_total = time.perf_counter()
        frame_bgr = self.cv2.imread(str(image_path))
        if frame_bgr is None:
            raise AvatarError(ErrorCode.INVALID_IMAGE_FORMAT, f"Could not read image: {image_path}")
        frame_rgb = frame_bgr[:, :, :3][:, :, ::-1]

        started_detect = time.perf_counter()
        boxes = self._detect_box_and_eyes(frame_rgb)
        detect_seconds = time.perf_counter() - started_detect
        if not boxes:
            raise AvatarError(ErrorCode.NO_FACE_DETECTED, f"No face detected in image: {image_path}")

        box, eyes = self._normalize_box(boxes)
        frame_batch = self.np.stack([frame_rgb])
        box_batch = self.np.stack([self.np.stack([box, eyes]).astype(self.np.float32)])

        started_recon = time.perf_counter()
        coeffs, bbox_list = self.model.process_imgs(frame_batch, box_batch[:, 0:1])
        coeffs[:, -4:] = self.torch.from_numpy(box_batch[:, 1]).to(coeffs.device)
        if self.device.type == "cuda":
            self.torch.cuda.synchronize(self.device)
        recon_seconds = time.perf_counter() - started_recon

        vertex_count = None
        face_count = None
        vertex_seconds = 0.0
        if compute_vertices:
            started_vertices = time.perf_counter()
            vertices, _vertices_projected, _normal, _colors = self.model.from_coeffs(coeffs, bbox_list)
            if self.device.type == "cuda":
                self.torch.cuda.synchronize(self.device)
            vertex_seconds = time.perf_counter() - started_vertices
            vertex_count = int(vertices.shape[1])
            face_count = int(len(self.model.fvd["tri"]))

        total_seconds = time.perf_counter() - started_total
        return {
            "mode": "faceverse_v4",
            "device": str(self.device),
            "root": str(self.root),
            "input_image": str(image_path),
            "coeff_shape": list(coeffs.shape),
            "bbox": bbox_list.tolist(),
            "vertex_count": vertex_count,
            "face_count": face_count,
            "timing": {
                "faceverse_v4_detect_seconds": detect_seconds,
                "faceverse_v4_recon_seconds": recon_seconds,
                "faceverse_v4_vertices_seconds": vertex_seconds,
                "faceverse_v4_total_seconds": total_seconds,
            },
        }

    def _select_device(self, device_name: str, *, allow_cpu_fallback: bool):
        requested = device_name.lower().strip()
        if requested == "auto":
            if self.torch.cuda.is_available():
                return self.torch.device("cuda")
            if allow_cpu_fallback:
                return self.torch.device("cpu")
            raise AvatarError(
                ErrorCode.MODEL_INFERENCE_FAILED,
                "FaceVerse_v4 is configured for GPU use, but CUDA is not available. "
                "Set FACEVERSE_V4_ALLOW_CPU_FALLBACK=true only for local smoke tests.",
            )
        return self.torch.device(requested)

    def _build_face_tracker(self):
        base_options = self.mp.tasks.BaseOptions
        face_landmarker_options = self.mp.tasks.vision.FaceLandmarkerOptions
        running_mode = self.mp.tasks.vision.RunningMode
        options = face_landmarker_options(
            base_options=base_options(model_asset_path=str(self.paths["face_landmarker.task"])),
            running_mode=running_mode.IMAGE,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
            num_faces=1,
        )
        return self.mp.tasks.vision.FaceLandmarker.create_from_options(options)

    def _detect_box_and_eyes(self, img):
        face_image = self.mp.Image(self.mp.ImageFormat.SRGB, img.astype(self.np.uint8))
        results = self.face_tracker.detect(face_image)
        if not results.face_landmarks:
            return []

        lms = results.face_landmarks[0]
        lms = self.np.array([(lmk.x, lmk.y) for lmk in lms])
        lms[:, 0] = lms[:, 0] * img.shape[1]
        lms[:, 1] = lms[:, 1] * img.shape[0]

        left_eye_norm = _norm(self.np, lms[362, :2] - lms[263, :2])
        left_eye_distance = _distance(self.np, lms[362, :2], lms[263, :2])
        leyex = (
            self.np.dot(lms[473] - (lms[263, :2] + lms[362, :2]) / 2, left_eye_norm)
            / left_eye_distance
            * 3
        )
        leyey = (
            self.np.dot(lms[473] - (lms[263, :2] + lms[362, :2]) / 2, left_eye_norm[[1, 0]])
            / left_eye_distance
            * -1.5
        )

        right_eye_norm = _norm(self.np, lms[33, :2] - lms[133, :2])
        right_eye_distance = _distance(self.np, lms[33, :2], lms[133, :2])
        reyex = (
            self.np.dot(lms[468] - (lms[33, :2] + lms[133, :2]) / 2, right_eye_norm)
            / right_eye_distance
            * 3
        )
        reyey = (
            self.np.dot(lms[468] - (lms[33, :2] + lms[133, :2]) / 2, right_eye_norm[[1, 0]])
            / right_eye_distance
            * -1.5
        )
        return [
            [self.np.min(lms[:, 0]), self.np.min(lms[:, 1]), self.np.max(lms[:, 0]), self.np.max(lms[:, 1])],
            [leyey, leyex, reyey, reyex],
        ]

    def _normalize_box(self, boxes):
        box = self.np.array(boxes).astype(self.np.float32)[0, :4]
        eyes = self.np.array(boxes).astype(self.np.float32)[1, :4]

        width = box[2] - box[0]
        height = box[3] - box[1]
        side_length = max(width, height)
        center_x = (box[0] + box[2]) // 2
        center_y = (box[1] + box[3]) // 2
        box[0] = center_x - side_length // 2
        box[1] = center_y - side_length // 2
        box[2] = center_x + side_length // 2
        box[3] = center_y + side_length // 2
        return box, eyes


def resolve_faceverse_v4_root(root: str | Path | None = None) -> Path:
    path = Path(root or settings.faceverse_v4_root)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def validate_faceverse_v4_assets(root: str | Path | None = None) -> dict[str, Path]:
    faceverse_root = resolve_faceverse_v4_root(root)
    data_dir = faceverse_root / "data"
    missing = [name for name in REQUIRED_FACEVERSE_V4_FILES if not (data_dir / name).exists()]
    if missing:
        raise AvatarError(
            ErrorCode.MODEL_INFERENCE_FAILED,
            "Missing FaceVerse_v4 asset files under "
            f"{data_dir}: {', '.join(missing)}. Download the model files before using ALGORITHM_MODE=faceverse_v4.",
        )
    return {name: data_dir / name for name in REQUIRED_FACEVERSE_V4_FILES}


def load_faceverse_v4_runner() -> FaceVerseV4Runner:
    return FaceVerseV4Runner()


def _distance(np_module, x, y):
    return np_module.sqrt(((x - y) ** 2).sum())


def _norm(np_module, x):
    denominator = np_module.sqrt((x**2).sum())
    if denominator == 0:
        return x
    return x / denominator
