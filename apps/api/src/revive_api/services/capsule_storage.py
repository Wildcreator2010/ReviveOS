"""S3-compatible capsule body storage using AWS Signature V4 and httpx."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx


class CapsuleStorage(Protocol):
    durable: bool

    async def put(self, key: str, content: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode(), hashlib.sha256).digest()


class S3CapsuleStorage:
    durable = True

    # An in-cluster object store must never be routed through ambient proxy env vars:
    # that breaks private endpoints and would hand signed requests to the proxy.
    CLIENT_OPTIONS: dict[str, Any] = {"timeout": 60.0, "trust_env": False}

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, region: str = "us-east-1") -> None:
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region

    def _signed_headers(self, method: str, key: str, content: bytes = b"") -> tuple[str, dict[str, str]]:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        path = f"/{quote(self.bucket, safe='')}/{quote(key, safe='/')}"
        url = self.endpoint + path
        payload_hash = hashlib.sha256(content).hexdigest()
        host = httpx.URL(url).host
        host_header = host
        headers = {
            "host": host_header,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_headers = "".join(
            f"{name}:{headers[name]}\n" for name in ("host", "x-amz-content-sha256", "x-amz-date")
        )
        canonical_request = "\n".join((method, path, "", canonical_headers, signed_headers, payload_hash))
        scope = f"{date}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            ("AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest())
        )
        key_date = _hmac(("AWS4" + self.secret_key).encode(), date)
        key_region = hmac.new(key_date, self.region.encode(), hashlib.sha256).digest()
        key_service = hmac.new(key_region, b"s3", hashlib.sha256).digest()
        signing_key = hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return url, headers

    async def put(self, key: str, content: bytes) -> None:
        url, headers = self._signed_headers("PUT", key, content)
        async with httpx.AsyncClient(**self.CLIENT_OPTIONS) as client:
            response = await client.put(url, content=content, headers=headers)
            response.raise_for_status()

    async def get(self, key: str) -> bytes:
        url, headers = self._signed_headers("GET", key)
        async with httpx.AsyncClient(**self.CLIENT_OPTIONS) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 404:
                raise FileNotFoundError(key)
            response.raise_for_status()
            return response.content

    async def delete(self, key: str) -> None:
        url, headers = self._signed_headers("DELETE", key)
        async with httpx.AsyncClient(**self.CLIENT_OPTIONS) as client:
            response = await client.delete(url, headers=headers)
            if response.status_code != 404:
                response.raise_for_status()


class MemoryCapsuleStorage:
    durable = False

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes) -> None:
        self.objects[key] = bytes(content)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise FileNotFoundError(key) from None

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


__all__ = ["CapsuleStorage", "MemoryCapsuleStorage", "S3CapsuleStorage"]
