from __future__ import annotations

import pytest

from tools.image_digests import validate


def test_production_compose_requires_runtime_digest_variables() -> None:
    validate("infra/compose/prod.docker-compose.yml")


def test_digest_validator_accepts_pinned_image(tmp_path) -> None:
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n"
        + "".join(
            f"  {name}:\n    image: example/{name}@sha256:${{{variable}:?required}}\n"
            for name, variable in (
                ("api", "API_DIGEST"),
                ("worker", "WORKER_DIGEST"),
                ("web", "WEB_DIGEST"),
                ("postgres", "POSTGRES_DIGEST"),
                ("redis", "REDIS_DIGEST"),
                ("caddy", "CADDY_DIGEST"),
            )
        ),
        encoding="utf-8",
    )
    validate(str(compose))


def test_digest_validator_rejects_tag_only_image(tmp_path) -> None:
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n"
        + "".join(
            f"  {name}:\n    image: example/{name}@sha256:${{{variable}:?required}}\n"
            for name, variable in (
                ("api", "API_DIGEST"),
                ("worker", "WORKER_DIGEST"),
                ("web", "WEB_DIGEST"),
                ("postgres", "POSTGRES_DIGEST"),
                ("redis", "REDIS_DIGEST"),
            )
        )
        + "  caddy:\n    image: example/caddy:latest\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="digest lock missing"):
        validate(str(compose))
