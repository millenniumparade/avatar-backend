"""Object-storage shaped service with a local filesystem backend."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import urlparse

from fastapi import UploadFile

from app.core.config import settings


class ObjectStorage:
    """Minimal object storage contract used by API and workers."""

    async def put_stream(self, key: str, stream: BinaryIO) -> str:
        raise NotImplementedError

    async def put_bytes(self, key: str, data: bytes) -> str:
        raise NotImplementedError

    async def put_json(self, key: str, payload: dict) -> str:
        raise NotImplementedError

    async def read_json(self, key: str) -> dict:
        raise NotImplementedError

    async def download_to_path(self, key: str, target_path: str | Path) -> str:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError

    async def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError


class LocalObjectStorage(ObjectStorage):
    """Filesystem-backed object storage implementation for local/dev use."""

    def __init__(self, storage_root: str | Path | None = None) -> None:
        root = Path(storage_root or settings.storage_root)
        self.storage_root = root.resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)

    async def put_stream(self, key: str, stream: BinaryIO) -> str:
        target = self._resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            shutil.copyfileobj(stream, output, length=1024 * 1024)
        return self._normalize_key(key)

    async def put_bytes(self, key: str, data: bytes) -> str:
        target = self._resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return self._normalize_key(key)

    async def put_json(self, key: str, payload: dict) -> str:
        target = self._resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
        return self._normalize_key(key)

    async def read_json(self, key: str) -> dict:
        source = self._resolve_key(key)
        with source.open("r", encoding="utf-8") as input_file:
            return json.load(input_file)

    async def download_to_path(self, key: str, target_path: str | Path) -> str:
        source = self._resolve_key(key)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as input_file, target.open("wb") as output:
            shutil.copyfileobj(input_file, output, length=1024 * 1024)
        return str(target)

    async def exists(self, key: str) -> bool:
        return self._resolve_key(key).exists()

    async def delete_prefix(self, prefix: str) -> None:
        normalized = self._normalize_key(prefix).rstrip("/")
        if not normalized:
            return

        target = self._resolve_key(normalized)
        if target.is_dir():
            shutil.rmtree(target)
            return
        if target.is_file():
            target.unlink()
            return

        parent = target.parent
        if not parent.exists():
            return
        prefix_name = target.name
        for child in parent.iterdir():
            if child.name.startswith(prefix_name):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

    def _resolve_key(self, key: str) -> Path:
        normalized = normalize_object_key(key)
        candidate = (self.storage_root / normalized).resolve()
        if candidate != self.storage_root and self.storage_root not in candidate.parents:
            raise ValueError(f"Storage key escapes storage root: {key}")
        return candidate

    def _normalize_key(self, key: str) -> str:
        return normalize_object_key(key)


class S3ObjectStorage(ObjectStorage):
    """S3-compatible object storage implementation for MinIO/S3/COS."""

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        bucket_name: str,
        region_name: str,
        secure: bool,
        client=None,
    ) -> None:
        self.bucket_name = bucket_name
        self.client = client or self._build_client(
            endpoint_url=endpoint_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region_name=region_name,
            secure=secure,
        )

    async def put_stream(self, key: str, stream: BinaryIO) -> str:
        object_key = normalize_object_key(key)
        self.client.upload_fileobj(stream, self.bucket_name, object_key)
        return object_key

    async def put_bytes(self, key: str, data: bytes) -> str:
        object_key = normalize_object_key(key)
        self.client.put_object(Bucket=self.bucket_name, Key=object_key, Body=data)
        return object_key

    async def put_json(self, key: str, payload: dict) -> str:
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        object_key = normalize_object_key(key)
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=object_key,
            Body=data,
            ContentType="application/json",
        )
        return object_key

    async def read_json(self, key: str) -> dict:
        object_key = normalize_object_key(key)
        response = self.client.get_object(Bucket=self.bucket_name, Key=object_key)
        with response["Body"] as body:
            return json.loads(body.read().decode("utf-8"))

    async def download_to_path(self, key: str, target_path: str | Path) -> str:
        object_key = normalize_object_key(key)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket_name, object_key, str(target))
        return str(target)

    async def exists(self, key: str) -> bool:
        object_key = normalize_object_key(key)
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    async def delete_prefix(self, prefix: str) -> None:
        normalized = normalize_object_key(prefix).rstrip("/")
        if not normalized:
            return

        continuation_token = None
        while True:
            kwargs = {"Bucket": self.bucket_name, "Prefix": normalized}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self.client.list_objects_v2(**kwargs)
            objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket_name, Delete={"Objects": objects})
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")

    def _build_client(
        self,
        *,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        region_name: str,
        secure: bool,
    ):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for STORAGE_BACKEND=minio") from exc

        normalized_endpoint = _normalize_endpoint(endpoint_url, secure=secure)
        return boto3.client(
            "s3",
            endpoint_url=normalized_endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
        )


class StorageService:
    """Read and write uploaded images, JSON results, and artifacts by object key."""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        *,
        object_storage: ObjectStorage | None = None,
    ) -> None:
        self.object_storage = object_storage or build_object_storage(storage_root=storage_root)

    async def save_upload_image(self, user_id: str, image_id: str, image: UploadFile) -> str:
        """Save a user-uploaded image and return its object key."""

        suffix = self._safe_suffix(image.filename) or self._suffix_from_content_type(image.content_type)
        key = self.build_uploaded_image_key(user_id=user_id, image_id=image_id, suffix=suffix)

        await image.seek(0)
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024 * 8) as stream:
            while chunk := await image.read(1024 * 1024):
                stream.write(chunk)
            stream.seek(0)
            await self.object_storage.put_stream(key, stream)
        await image.seek(0)
        return key

    async def save_upload_bytes(
        self,
        *,
        user_id: str,
        image_id: str,
        data: bytes,
        filename: str | None,
        content_type: str | None,
    ) -> str:
        """Save already validated upload bytes and return the object key."""

        suffix = self._safe_suffix(filename) or self._suffix_from_content_type(content_type)
        key = self.build_uploaded_image_key(user_id=user_id, image_id=image_id, suffix=suffix)
        return await self.object_storage.put_bytes(key, data)

    async def save_upload_stream(
        self,
        *,
        user_id: str,
        image_id: str,
        stream: BinaryIO,
        filename: str | None,
        content_type: str | None,
    ) -> str:
        """Save a validated upload stream and return the object key."""

        suffix = self._safe_suffix(filename) or self._suffix_from_content_type(content_type)
        key = self.build_uploaded_image_key(user_id=user_id, image_id=image_id, suffix=suffix)
        return await self.object_storage.put_stream(key, stream)

    async def save_json(self, key: str, payload: dict) -> str:
        """Save a JSON payload and return its object key."""

        return await self.object_storage.put_json(key, payload)

    async def read_json(self, key: str) -> dict:
        """Read a JSON payload by object key."""

        return await self.object_storage.read_json(key)

    async def save_bytes(self, key: str, data: bytes) -> str:
        """Save raw bytes to an object key."""

        return await self.object_storage.put_bytes(key, data)

    async def save_stream(self, key: str, stream: BinaryIO) -> str:
        """Save a binary stream to an object key."""

        return await self.object_storage.put_stream(key, stream)

    async def get_local_path(self, key: str) -> str:
        """Download an object to a temporary local path for algorithms requiring files."""

        suffix = Path(PurePosixPath(normalize_object_key(key)).name).suffix
        handle = tempfile.NamedTemporaryFile(prefix="avatar-object-", suffix=suffix, delete=False)
        target_path = handle.name
        handle.close()
        return await self.object_storage.download_to_path(key, target_path)

    async def exists(self, key: str) -> bool:
        """Return whether an object key exists."""

        return await self.object_storage.exists(key)

    async def delete_prefix(self, prefix: str) -> None:
        """Delete all objects under a key prefix."""

        await self.object_storage.delete_prefix(prefix)

    def build_uploaded_image_key(self, *, user_id: str, image_id: str, suffix: str = ".jpg") -> str:
        """Build the canonical object key for an original upload."""

        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return normalize_object_key(f"users/{user_id}/images/{image_id}/original{suffix.lower()}")

    def build_result_json_key(self, *, user_id: str, job_id: str) -> str:
        """Build the canonical object key for a generated HumanInfo payload."""

        return normalize_object_key(f"users/{user_id}/jobs/{job_id}/HumanInfo.json")

    def build_artifact_key(self, *, user_id: str, job_id: str, filename: str) -> str:
        """Build an object key for a job artifact."""

        safe_name = PurePosixPath(filename).name
        return normalize_object_key(f"users/{user_id}/jobs/{job_id}/artifacts/{safe_name}")

    def _safe_suffix(self, filename: str | None) -> str:
        if not filename:
            return ""
        suffix = Path(filename).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            return suffix
        return ""

    def _suffix_from_content_type(self, content_type: str | None) -> str:
        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }
        return mapping.get(content_type or "", ".jpg")


def get_storage_service() -> StorageService:
    """Return the configured storage service."""

    return StorageService()


def normalize_object_key(key: str) -> str:
    normalized = key.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Invalid storage key: {key}")
    return path.as_posix()


def build_object_storage(storage_root: str | Path | None = None) -> ObjectStorage:
    backend = settings.storage_backend.lower()
    if backend == "local":
        return LocalObjectStorage(storage_root)
    if backend in {"minio", "s3", "cos"}:
        return S3ObjectStorage(
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            bucket_name=settings.s3_bucket_name,
            region_name=settings.s3_region_name,
            secure=settings.s3_secure,
        )
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")


def _normalize_endpoint(endpoint_url: str | None, *, secure: bool) -> str | None:
    if not endpoint_url:
        return None
    parsed = urlparse(endpoint_url)
    if parsed.scheme:
        return endpoint_url
    scheme = "https" if secure else "http"
    return f"{scheme}://{endpoint_url}"
