"""Readiness must cover every dependency the API cannot degrade around."""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.deps import readiness_probes, run_probe
from revive_api.main import create_app


class _Handler(BaseHTTPRequestHandler):
    status = 200

    def log_message(self, *args) -> None:
        return

    def do_HEAD(self) -> None:
        self.send_response(self.status)
        self.end_headers()


def _serve(status: int):
    handler = type("Handler", (_Handler,), {"status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _run(probe: Any) -> bool:
    return asyncio.run(run_probe(probe))


@pytest.mark.parametrize(("status", "ready"), [(200, True), (403, True), (404, False), (503, False)])
def test_object_storage_probe_fails_closed_on_missing_bucket(status: int, ready: bool) -> None:
    server, thread = _serve(status)
    try:
        config = Config(
            s3_endpoint=f"http://127.0.0.1:{server.server_address[1]}",
            s3_bucket="capsules",
        )
        probe = readiness_probes(config)["object_storage"]
        assert _run(probe) is ready
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_object_storage_probe_is_unreachable_when_nothing_listens() -> None:
    config = Config(s3_endpoint="http://127.0.0.1:1", s3_bucket="capsules")
    assert _run(readiness_probes(config)["object_storage"]) is False


def test_readyz_reports_object_storage_component() -> None:
    server, thread = _serve(200)
    try:
        config = Config(
            jwt_secret="test-secret-at-least-32-bytes-long",
            s3_endpoint=f"http://127.0.0.1:{server.server_address[1]}",
            s3_bucket="capsules",
        )
        client = TestClient(create_app(config, probes=readiness_probes(config)))
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["components"]["object_storage"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_readyz_fails_closed_when_object_storage_is_down() -> None:
    config = Config(
        jwt_secret="test-secret-at-least-32-bytes-long",
        s3_endpoint="http://127.0.0.1:1",
        s3_bucket="capsules",
    )
    client = TestClient(create_app(config, probes=readiness_probes(config)))
    response = client.get("/readyz")
    assert response.status_code == 503
    components = response.json()["error"]["details"]["detail"]["components"]
    assert components["object_storage"] == "unavailable"
