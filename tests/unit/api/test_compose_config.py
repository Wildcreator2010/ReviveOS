from pathlib import Path


def test_compose_requires_all_release_image_paths_and_digests() -> None:
    compose = Path("infra/compose/prod.docker-compose.yml").read_text(encoding="utf-8")
    for variable in (
        "REVIVE_API_IMAGE",
        "REVIVE_WORKER_IMAGE",
        "REVIVE_WEB_IMAGE",
        "API_DIGEST",
        "WORKER_DIGEST",
        "WEB_DIGEST",
        "POSTGRES_DIGEST",
        "REDIS_DIGEST",
        "CADDY_DIGEST",
    ):
        assert f"${{{variable}:?" in compose


def test_compose_env_template_documents_required_release_inputs() -> None:
    template = Path("infra/envs/compose.env.template").read_text(encoding="utf-8")
    for variable in (
        "REVIVE_API_IMAGE",
        "REVIVE_WORKER_IMAGE",
        "REVIVE_WEB_IMAGE",
        "API_DIGEST",
        "WORKER_DIGEST",
        "WEB_DIGEST",
        "POSTGRES_DIGEST",
        "REDIS_DIGEST",
        "CADDY_DIGEST",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "REVIVE_DOMAIN",
        "DOCKER_GID",
    ):
        assert f"{variable}=" in template
