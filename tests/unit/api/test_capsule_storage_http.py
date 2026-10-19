"""Real HTTP round-trip against the S3-compatible capsule adapter.

Docker/MinIO are unavailable in the sandbox, so this stands up a bare HTTP server and
drives the exact same code path the production worker uses (SigV4 path-style requests).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from revive_api.services.capsule_storage import S3CapsuleStorage


class _Store:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[dict[str, str]] = []


class _Handler(BaseHTTPRequestHandler):
    store: _Store

    def log_message(self, *args) -> None:  # keep the test output clean
        return

    def _record(self) -> None:
        self.store.requests.append(
            {"method": self.command, "path": self.path, "authorization": self.headers.get("authorization", "")}
        )

    def do_PUT(self) -> None:
        self._record()
        length = int(self.headers.get("content-length", "0"))
        self.store.objects[self.path] = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        self._record()
        payload = self.store.objects.get(self.path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_DELETE(self) -> None:
        self._record()
        self.store.objects.pop(self.path, None)
        self.send_response(204)
        self.end_headers()


@pytest.fixture
def s3_server():
    store = _Store()
    handler = type("Handler", (_Handler,), {"store": store})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield store, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_s3_capsule_storage_round_trip_over_real_http(s3_server) -> None:
    store, port = s3_server
    storage = S3CapsuleStorage(
        endpoint=f"http://127.0.0.1:{port}",
        access_key="AKIDEXAMPLE",
        secret_key="secret",
        bucket="capsules",
    )
    key = "capsules/user_1/rev_capsule_1.revive"
    content = b"capsule bytes"

    await storage.put(key, content)
    assert store.objects[f"/capsules/{key}"] == content

    assert await storage.get(key) == content

    await storage.delete(key)
    assert store.objects == {}

    # Deleting a missing object is idempotent, not an error.
    await storage.delete(key)

    methods = [entry["method"] for entry in store.requests]
    assert methods == ["PUT", "GET", "DELETE", "DELETE"]
    assert all(entry["authorization"].startswith("AWS4-HMAC-SHA256 ") for entry in store.requests)
