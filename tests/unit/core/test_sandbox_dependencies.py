"""Dependencies are installed while the image is built; runtime stays offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from revive_core.sandbox.dep_solver import PypiVersionProvider
from revive_core.sandbox.image_matrix import ImagePlan
from revive_core.sandbox.port_impl import (
    _pin_image_plan,
    dependency_specs,
    dockerfile_with_dependencies,
    sandbox_security_kwargs,
)


def test_dependency_specs_are_validated_and_deduplicated() -> None:
    genome = {
        "dependencies": [
            {"name": "requests", "version": "2.32.3", "source": "pypi"},
            {"name": "requests", "version": "2.32.3", "source": "pypi"},
            {"name": "numpy", "version": ">=1.26", "source": "requirements"},
            {"name": "click", "version": "unknown", "source": "pypi"},
            {"name": "flask", "version": "*", "source": "inference"},
            {"name": "evil; rm -rf /", "version": "1.0", "source": "pypi"},
            {"name": "gitdep", "version": "1.0", "source": "git"},
        ]
    }

    assert dependency_specs(genome) == ["requests==2.32.3", "numpy>=1.26", "click", "flask"]


def test_dependency_install_runs_before_the_privilege_drop() -> None:
    dockerfile = 'FROM ubuntu:22.04\nUSER 1000:1000\nCMD ["bash"]\n'

    rendered = dockerfile_with_dependencies(dockerfile, ["requests==2.32.3"])

    assert rendered.index("pip install") < rendered.index("USER 1000:1000")
    assert "requests==2.32.3" in rendered


def test_tmpfs_options_do_not_include_the_mount_path() -> None:
    kwargs = sandbox_security_kwargs("rev_job")

    assert kwargs["tmpfs"]["/tmp"] == "rw,noexec,nosuid,size=256m"
    assert "size=512m" in kwargs["tmpfs"]["/workspace"]
    assert kwargs["network_disabled"] is True
    assert kwargs["security_opt"] == ["no-new-privileges"]


def test_pypi_fallback_prefers_the_newest_eligible_release() -> None:
    class Release:
        def __init__(self, version: str, offset: int) -> None:
            self.version = version
            self.uploaded_at = datetime(2018, 1, 1, tzinfo=UTC) + timedelta(days=offset)

    class Client:
        def versions_before(self, name: str, cutoff: datetime) -> list[Release]:
            return [Release("1.0.0", 0), Release("1.1.0", 1), Release("1.2.0", 2)]

    provider = PypiVersionProvider(Client())

    assert provider.candidates("demo", "1.2.0", datetime(2019, 1, 1, tzinfo=UTC)) == [
        "1.2.0",
        "1.1.0",
        "1.0.0",
    ]


def test_image_plan_is_pinned_when_a_digest_can_be_resolved(monkeypatch) -> None:
    plan = ImagePlan(
        os_image="ubuntu:22.04",
        os_release="22.04",
        os_digest=None,
        digest_expected=True,
        python_version="3.11",
        python_install="apt",
        channel="apt",
        extra_apt=(),
        conda_env_yaml=None,
        conda_channels=(),
        template="base-py3.11.Dockerfile.tpl",
    )
    digest = "sha256:" + "a" * 64
    monkeypatch.setattr("revive_core.sandbox.port_impl.resolve_digest", lambda reference: digest)

    assert _pin_image_plan(plan).os_digest == digest
