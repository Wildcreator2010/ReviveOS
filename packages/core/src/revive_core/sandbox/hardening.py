"""Docker HostConfig policy for production sandboxes.

Docker execution tests are marked requires_docker because they need a daemon.
"""

from __future__ import annotations

from pathlib import Path


def image_ref(image: str) -> str:
    if "@sha256:" not in image:
        raise ValueError("production sandbox images must be digest-pinned")
    return image


def host_config(image: str) -> dict[str, object]:
    """Return docker-py-compatible restrictive settings."""
    image_ref(image)
    return {
        "read_only": True,
        "tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m", "/workspace": "rw,noexec,nosuid,size=512m"},
        "security_opt": ["no-new-privileges", "seccomp:revive"],
        "cap_drop": ["ALL"],
        "pids_limit": 256,
        "privileged": False,
        "network_disabled": True,
        "user": "1000:1000",
    }


SECCOMP_PROFILE = Path("infra/sandbox/seccomp.revive.json")
