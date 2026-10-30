from revive_core.sandbox.executor import SANDBOX_USER, TMPFS_SPEC
from revive_core.sandbox.hardening import host_config
from revive_core.sandbox.port_impl import sandbox_security_kwargs


def test_host_config_is_restrictive():
    config = host_config("python@sha256:" + "a" * 64)
    assert config["read_only"] is True
    assert config["cap_drop"] == ["ALL"]
    assert config["pids_limit"] == 256


def test_runtime_sandbox_kwargs_match_the_hardening_contract():
    config = sandbox_security_kwargs("job-hardening")
    assert config["read_only"] is True
    assert config["network_disabled"] is True
    assert config["user"] == SANDBOX_USER
    assert config["cap_drop"] == ["ALL"]
    assert config["pids_limit"] == 256
    assert config["security_opt"] == ["no-new-privileges"]
    assert config["tmpfs"]["/tmp"] == TMPFS_SPEC
    assert "/workspace" in config["tmpfs"]
    assert "size=512m" in config["tmpfs"]["/workspace"]
    assert sandbox_security_kwargs("job-hardening", seccomp_profile="/host/seccomp.json")["security_opt"] == [
        "no-new-privileges",
        "seccomp:/host/seccomp.json",
    ]
