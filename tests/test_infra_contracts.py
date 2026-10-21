"""Static contract tests for the CI gate, pre-commit config and dev compose.

These tests never touch the Docker daemon: they parse the committed config files.
The one test that does need a daemon is marked `requires_docker` and is skipped
inside the DSH sandbox with an explicit reason.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "infra" / "compose" / "dev.docker-compose.yml"
PROD_COMPOSE_FILE = REPO_ROOT / "infra" / "compose" / "prod.docker-compose.yml"
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRECOMMIT_FILE = REPO_ROOT / ".pre-commit-config.yaml"


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves cls.__module__ via sys.modules
    spec.loader.exec_module(module)
    return module


def test_pre_commit_is_local_only_and_never_skips() -> None:
    config = load_yaml(PRECOMMIT_FILE)
    assert config["fail_fast"] is False
    hook_ids: list[str] = []
    for repo in config["repos"]:
        assert repo["repo"] == "local", "hooks must not need network to install"
        for hook in repo["hooks"]:
            assert "skip" not in hook
            assert hook["language"] == "system"
            entry = str(hook["entry"])
            assert "--no-verify" not in entry
            hook_ids.append(hook["id"])
    assert hook_ids == [
        "ruff-check",
        "ruff-format",
        "mypy",
        "pytest-unit",
        "jsonschema-contracts",
        "global-rules",
    ]


def test_ci_runs_the_five_gates_in_order_and_never_deploys() -> None:
    text = CI_FILE.read_text(encoding="utf-8")
    markers = [
        "uv run ruff check",
        "uv run ruff format --check",
        "uv run mypy",
        "uv run pytest -q tests",
        "tools/check_contracts.py",
        "tools/check_global_rules.py .",
    ]
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions), "CI gate order is contractual"
    lowered = text.lower()
    for forbidden in ("deploy", "kubectl", "helm", "aws ecs", "flyctl", "no-verify"):
        assert forbidden not in lowered


def test_dev_compose_contract() -> None:
    compose = load_yaml(COMPOSE_FILE)
    services = compose["services"]
    assert {"postgres", "redis", "minio"} <= set(services)

    for name in ("postgres", "redis", "minio"):
        service = services[name]
        assert service.get("healthcheck", {}).get("test"), f"{name} needs a healthcheck"
        assert service.get("ports"), f"{name} needs a published port"
        assert not service.get("privileged")
        assert not service.get("cap_add")

    assert services["postgres"]["image"] == "pgvector/pgvector:pg16"
    assert "5432:5432" in services["postgres"]["ports"]
    assert "6379:6379" in services["redis"]["ports"]
    assert "9000:9000" in services["minio"]["ports"]
    assert "9001:9001" in services["minio"]["ports"]

    init = services["minio-init"]
    assert "bootstrap" in init.get("profiles", []), "plain `up -d` must start only 3 services"

    dumped = yaml.safe_dump(compose)
    assert "capsules" in dumped
    assert "artifacts" in dumped
    assert "C:\\" not in dumped and "/mnt/" not in dumped, "no host absolute paths"


def test_prod_compose_uses_a_pgvector_capable_postgres() -> None:
    compose = load_yaml(PROD_COMPOSE_FILE)
    image = compose["services"]["postgres"]["image"]
    assert image.startswith("pgvector/pgvector:pg16@sha256:"), (
        "migration 0002 runs CREATE EXTENSION vector; stock postgres:16 cannot serve it"
    )


def test_prod_compose_schedules_the_sweeper_and_wires_capsule_upload() -> None:
    compose = load_yaml(PROD_COMPOSE_FILE)
    services = compose["services"]
    assert "beat" in services, "without beat the orphan-sandbox schedule never fires"
    assert "beat" in services["beat"]["command"]
    assert services["worker"]["environment"]["REVIVE_API_URL"] == "http://api:8000"
    assert services["worker"].get("depends_on", {}).get("api", {}).get("condition") == "service_healthy"


def test_worker_and_sandbox_images_ship_git() -> None:
    worker = (REPO_ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
    assert "git" in worker and "apt-get install" in worker, (
        "the worker clones repositories and applies patches with git"
    )
    assert "COPY infra/sandbox" in worker, "DockerExecutionPort needs the sandbox Dockerfile templates"
    assert "COPY schemas" in worker, "scoring/capsule validation reads schemas/ at runtime"
    assert "WORKDIR /work" in worker, "the non-root worker needs a writable working directory"

    partials = REPO_ROOT / "infra" / "sandbox" / "partials"
    for name in ("apt.j2", "conda.j2", "deadsnakes.j2", "source.j2"):
        text = (partials / name).read_text(encoding="utf-8")
        assert "git" in text, f"{name} must install git for DockerExecutionPort.apply_patch"


def test_contracts_gate_is_green_on_the_repository() -> None:
    assert load_tool("check_contracts").main([str(REPO_ROOT)]) == 0


def test_contracts_gate_turns_red_on_a_broken_fixture(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    (schema_dir / "demo.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["a"],
                "additionalProperties": False,
                "properties": {"a": {"type": "integer"}},
            }
        ),
        encoding="utf-8",
    )
    fixtures = tmp_path / "tests" / "contracts" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "demo-valid.json").write_text("{}", encoding="utf-8")
    assert load_tool("check_contracts").main([str(tmp_path)]) == 1


@pytest.mark.requires_docker
def test_compose_stack_comes_up_healthy() -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--quiet"],
        check=True,
        timeout=180,
    )
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"],
        check=True,
        timeout=600,
    )
    try:
        ps = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert "healthy" in ps.stdout
    finally:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down"],
            check=False,
            timeout=300,
        )
