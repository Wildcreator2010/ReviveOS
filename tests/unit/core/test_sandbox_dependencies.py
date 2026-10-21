"""Dependencies are installed while the image is built; runtime stays offline."""

from __future__ import annotations

from revive_core.sandbox.port_impl import dependency_specs, dockerfile_with_dependencies, sandbox_security_kwargs


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

    assert kwargs["tmpfs"] == {"/tmp": "rw,noexec,nosuid,size=256m"}
    assert kwargs["network_disabled"] is True
    assert kwargs["security_opt"] == ["no-new-privileges"]
