"""Validate that production compose uses immutable, non-placeholder digests."""

from __future__ import annotations

import re
import sys
from pathlib import Path

DIGEST = re.compile(r"@sha256:(?:\$\{[A-Z0-9_]+(?::[^}]*)?\}|([0-9a-f]{64}))")
ZERO = "0" * 64


def validate(path: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    image_lines = [line.strip() for line in text.splitlines() if "image:" in line]
    if not image_lines:
        raise SystemExit("no production images found")
    services = re.split(r"(?m)^  ([a-z][a-z0-9_-]*):\s*$", text)
    image_by_service = {
        services[index]: re.search(r"(?m)^    image:\s*(.+)$", services[index + 1]).group(1)
        for index in range(1, len(services) - 1, 2)
        if re.search(r"(?m)^    image:\s*(.+)$", services[index + 1])
    }
    expected = {"api", "worker", "web", "postgres", "redis", "caddy"}
    if missing := sorted(expected - image_by_service.keys()):
        raise SystemExit("production image definitions missing: " + ", ".join(missing))
    for service, image in image_by_service.items():
        match = DIGEST.search(image)
        if match is None:
            raise SystemExit(f"digest lock missing for {service}: {image}")
        if match.group(1) == ZERO:
            raise SystemExit(f"placeholder digest is not deployable for {service}: {image}")
    expected_digest_vars = {
        "api": "API_DIGEST",
        "worker": "WORKER_DIGEST",
        "web": "WEB_DIGEST",
        "postgres": "POSTGRES_DIGEST",
        "redis": "REDIS_DIGEST",
        "caddy": "CADDY_DIGEST",
    }
    for service, variable in expected_digest_vars.items():
        if f"${{{variable}:?" not in image_by_service[service]:
            raise SystemExit(f"{service} image must require {variable}")


if __name__ == "__main__":
    validate(sys.argv[1] if len(sys.argv) > 1 else "infra/compose/prod.docker-compose.yml")
