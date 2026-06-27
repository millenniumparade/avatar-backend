"""Hash utilities."""

from __future__ import annotations

import hashlib
from pathlib import Path


def calculate_sha256(file_path: str) -> str:
    """Calculate a file's SHA-256 digest."""

    digest = hashlib.sha256()
    with Path(file_path).open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calculate_bytes_sha256(data: bytes) -> str:
    """Calculate a SHA-256 digest for in-memory bytes."""

    return hashlib.sha256(data).hexdigest()
