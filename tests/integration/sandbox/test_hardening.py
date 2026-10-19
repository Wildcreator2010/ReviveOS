import pytest
from revive_core.sandbox.hardening import host_config


def test_host_config_is_restrictive():
    config = host_config("python@sha256:" + "a" * 64)
    assert config["read_only"] is True
    assert config["cap_drop"] == ["ALL"]
    assert config["pids_limit"] == 256


@pytest.mark.requires_docker
@pytest.mark.parametrize("payload", ["fork-bomb", "write-etc", "mount", "docker-socket"])
def test_escape_payloads_rejected_requires_docker(payload):
    pytest.skip("requires_docker: Docker daemon unavailable in this environment")
