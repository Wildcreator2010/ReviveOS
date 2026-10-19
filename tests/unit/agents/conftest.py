"""Shared fixtures for the agents unit tests.

Every test runs with LLM/job environment variables cleared so a developer's
real configuration can never influence a unit test, and no test may hit the
network: adapters are exercised through httpx.MockTransport.
"""

from __future__ import annotations

import os

import pytest

_PREFIXES = ("REVIVE_LLM__", "REVIVE_JOB__", "REVIVE_DEBUG_LLM", "REVIVE_GIT_BIN")


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    yield
