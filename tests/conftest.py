"""Shared pytest configuration for the ReviveOS test suite.

Two sandbox facts shape this file:

* Docker-dependent tests are skipped: the Docker CLI is present but the Windows
  named pipe to the daemon is blocked. Set `REVIVE_DOCKER_AVAILABLE=1` from an
  unsandboxed terminal to actually run them.
* pytest's own tmp_path factory cannot be used: the DSH sandbox denies writes
  under the machine temp root and refuses to revisit a directory created by an
  earlier process, so the factory's basetemp cleanup dies with WinError 5.
  `tmp_path` is therefore re-implemented over a per-process workspace root.
"""

from __future__ import annotations

import itertools
import os
import re
import time
from pathlib import Path

import pytest

DOCKER_SKIP_REASON = (
    "Docker daemon unreachable from the DSH sandbox (Windows named pipe blocked); "
    "set REVIVE_DOCKER_AVAILABLE=1 and run from an unsandboxed terminal"
)

# Created and consumed by one pytest process; never revisited by a later one.
RUN_ROOT = Path(__file__).resolve().parents[1] / ".pytest-work" / f"run-{os.getpid()}-{int(time.time())}"
_test_index = itertools.count()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_docker: needs a reachable Docker daemon (skipped inside the DSH sandbox)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("REVIVE_DOCKER_AVAILABLE") == "1":
        return
    skipper = pytest.mark.skip(reason=DOCKER_SKIP_REASON)
    for item in items:
        if "requires_docker" in item.keywords:
            item.add_marker(skipper)


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    """Sandbox-safe replacement for pytest's built-in `tmp_path` fixture."""

    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid).strip("_")[-100:]
    path = RUN_ROOT / f"{next(_test_index):03d}-{label or 'test'}"
    path.mkdir(parents=True, exist_ok=True)
    return path
