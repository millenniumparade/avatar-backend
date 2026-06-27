"""Image utilities."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from PIL import Image


def validate_image_extension(filename: str, allowed_extensions: set[str]) -> bool:
    """Validate an uploaded image extension."""

    suffix = Path(filename or "").suffix.lower().lstrip(".")
    return bool(suffix) and suffix in {extension.lower().lstrip(".") for extension in allowed_extensions}


def read_image_size(file_path: str) -> tuple[int, int]:
    """Read image width and height."""

    with Image.open(file_path) as image:
        return image.size


def read_image_size_from_bytes(data: bytes) -> tuple[int, int]:
    """Read image width and height from upload bytes without resizing."""

    with Image.open(BytesIO(data)) as image:
        return image.size


def read_image_size_from_stream(stream: BinaryIO) -> tuple[int, int]:
    """Read image width and height from a binary stream without loading it fully."""

    with Image.open(stream) as image:
        return image.size
