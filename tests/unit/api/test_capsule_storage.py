from __future__ import annotations

import hashlib

import pytest
from revive_api.services.capsule_storage import MemoryCapsuleStorage, S3CapsuleStorage


@pytest.mark.asyncio
async def test_memory_capsule_storage_round_trip() -> None:
    storage = MemoryCapsuleStorage()
    await storage.put("capsules/u1/c1.revive", b"payload")
    assert await storage.get("capsules/u1/c1.revive") == b"payload"
    assert await storage.exists("capsules/u1/c1.revive") is True
    chunks = [chunk async for chunk in storage.stream("capsules/u1/c1.revive")]
    assert b"".join(chunks) == b"payload"
    await storage.delete("capsules/u1/c1.revive")
    with pytest.raises(FileNotFoundError):
        await storage.get("capsules/u1/c1.revive")
    assert await storage.exists("capsules/u1/c1.revive") is False
    assert storage.durable is False


def test_s3_storage_signs_path_style_requests_with_payload_hash() -> None:
    storage = S3CapsuleStorage(
        endpoint="http://minio:9000",
        access_key="AKIDEXAMPLE",
        secret_key="secret",
        bucket="capsules",
        region="us-east-1",
    )
    content = b"capsule bytes"
    url, headers = storage._signed_headers("PUT", "capsules/u1/c1.revive", content)

    assert url == "http://minio:9000/capsules/capsules/u1/c1.revive"
    assert headers["x-amz-content-sha256"] == hashlib.sha256(content).hexdigest()
    authorization = headers["authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in authorization
    assert "Signature=" in authorization


def test_s3_storage_marks_itself_durable() -> None:
    storage = S3CapsuleStorage("http://minio:9000", "a", "b", "bucket")
    assert storage.durable is True
