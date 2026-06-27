from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import UploadFile
from PIL import Image
import pytest

from app.services.storage_service import LocalObjectStorage, S3ObjectStorage, StorageService
from app.utils.hash_utils import calculate_bytes_sha256, calculate_sha256
from app.utils.image_utils import read_image_size, validate_image_extension


def make_png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 12), color=(255, 0, 0)).save(output, format="PNG")
    return output.getvalue()


def run_async(coro):
    return asyncio.run(coro)


def test_save_upload_image_and_json_round_trip(tmp_path) -> None:
    service = StorageService(storage_root=tmp_path)
    image_bytes = make_png_bytes()
    upload = UploadFile(filename="face.png", file=BytesIO(image_bytes))
    upload.headers = {"content-type": "image/png"}

    image_key = run_async(service.save_upload_image("user-1", "image-1", upload))
    image_path = run_async(service.get_local_path(image_key))

    assert image_key == "users/user-1/images/image-1/original.png"
    assert calculate_sha256(image_path) == calculate_bytes_sha256(image_bytes)
    assert read_image_size(image_path) == (16, 12)

    json_key = service.build_result_json_key(user_id="user-1", job_id="job-1")
    saved_key = run_async(service.save_json(json_key, {"schema_version": "1.0", "parts": {"hair": 1}}))

    assert saved_key == "users/user-1/jobs/job-1/HumanInfo.json"
    assert run_async(service.read_json(saved_key)) == {"schema_version": "1.0", "parts": {"hair": 1}}
    assert run_async(service.exists(saved_key)) is True


def test_delete_prefix_removes_nested_objects(tmp_path) -> None:
    service = StorageService(storage_root=tmp_path)
    run_async(service.save_bytes("users/user-1/jobs/job-1/a.txt", b"a"))
    run_async(service.save_bytes("users/user-1/jobs/job-1/artifacts/b.txt", b"b"))
    run_async(service.save_bytes("users/user-1/jobs/job-2/c.txt", b"c"))

    run_async(service.delete_prefix("users/user-1/jobs/job-1/"))

    assert run_async(service.exists("users/user-1/jobs/job-1/a.txt")) is False
    assert run_async(service.exists("users/user-1/jobs/job-1/artifacts/b.txt")) is False
    assert run_async(service.exists("users/user-1/jobs/job-2/c.txt")) is True


def test_storage_key_cannot_escape_root(tmp_path) -> None:
    service = StorageService(storage_root=tmp_path)

    with pytest.raises(ValueError):
        run_async(service.save_bytes("../escape.txt", b"bad"))

    with pytest.raises(ValueError):
        run_async(service.get_local_path("users/../../escape.txt"))


def test_local_object_storage_downloads_to_requested_path(tmp_path) -> None:
    storage = LocalObjectStorage(storage_root=tmp_path)
    key = run_async(storage.put_bytes("users/user-1/images/image-1/original.png", make_png_bytes()))
    target = tmp_path / "downloaded" / "face.png"

    downloaded_path = run_async(storage.download_to_path(key, target))

    assert downloaded_path == str(target)
    assert calculate_sha256(downloaded_path) == calculate_sha256(str(tmp_path / key))


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_fileobj(self, stream, bucket, key) -> None:
        self.objects[(bucket, key)] = stream.read()

    def put_object(self, **kwargs) -> None:
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs):
        data = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": BytesIO(data)}

    def download_file(self, bucket, key, filename) -> None:
        with open(filename, "wb") as output:
            output.write(self.objects[(bucket, key)])

    def head_object(self, **kwargs) -> None:
        if (kwargs["Bucket"], kwargs["Key"]) not in self.objects:
            error = Exception("not found")
            error.response = {"Error": {"Code": "404"}}
            raise error

    def list_objects_v2(self, **kwargs):
        bucket = kwargs["Bucket"]
        prefix = kwargs["Prefix"]
        contents = [{"Key": key} for item_bucket, key in self.objects if item_bucket == bucket and key.startswith(prefix)]
        return {"Contents": contents, "IsTruncated": False}

    def delete_objects(self, **kwargs) -> None:
        bucket = kwargs["Bucket"]
        for item in kwargs["Delete"]["Objects"]:
            self.objects.pop((bucket, item["Key"]), None)


def test_s3_object_storage_uses_object_keys(tmp_path) -> None:
    client = FakeS3Client()
    storage = S3ObjectStorage(
        endpoint_url="http://minio:9000",
        access_key_id="avatar_minio",
        secret_access_key="avatar_minio_secret",
        bucket_name="avatar",
        region_name="us-east-1",
        secure=False,
        client=client,
    )

    key = run_async(storage.put_bytes("users/user-1/a.txt", b"a"))
    assert key == "users/user-1/a.txt"
    assert run_async(storage.exists(key)) is True

    json_key = run_async(storage.put_json("users/user-1/HumanInfo.json", {"hair": 1}))
    assert run_async(storage.read_json(json_key)) == {"hair": 1}

    target = tmp_path / "a.txt"
    run_async(storage.download_to_path(key, target))
    assert target.read_bytes() == b"a"

    run_async(storage.delete_prefix("users/user-1/"))
    assert run_async(storage.exists(key)) is False


def test_image_extension_validation() -> None:
    assert validate_image_extension("face.JPG", {"jpg", "png"}) is True
    assert validate_image_extension("face.gif", {"jpg", "png"}) is False
    assert validate_image_extension("face", {"jpg", "png"}) is False
