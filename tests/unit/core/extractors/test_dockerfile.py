"""Dockerfile FROM extraction with multi-stage builder handling."""

from __future__ import annotations

from revive_core.archaeology.evidence import extract_from_text
from revive_core.archaeology.extractors import dockerfile


def test_matches_dockerfile_names():
    assert dockerfile.matches("Dockerfile")
    assert dockerfile.matches("Dockerfile.dev")
    assert dockerfile.matches("ops/service.Dockerfile")
    assert not dockerfile.matches("docker-compose.yml")


def test_single_stage_python_image():
    facts = extract_from_text("Dockerfile", "FROM python:3.9-slim\nRUN pip install .\n")[0].facts
    assert facts["base_image"] == "python:3.9-slim"
    assert facts["python_version"] == "3.9"
    assert facts["os_distro"] == "debian"


def test_multi_stage_picks_first_non_builder():
    text = (
        "FROM python:3.9 AS builder\n"
        "RUN pip wheel .\n"
        "FROM python:3.9-slim AS runtime\n"
        "COPY --from=builder /wheels /wheels\n"
    )
    facts = extract_from_text("Dockerfile", text)[0].facts
    assert facts["base_image"] == "python:3.9-slim"
    assert [stage["is_builder"] for stage in facts["dockerfile_stages"]] == [True, False]


def test_cuda_base_image():
    text = "FROM nvidia/cuda:11.2.0-cudnn8-runtime-ubuntu20.04\n"
    facts = extract_from_text("Dockerfile", text)[0].facts
    assert facts["cuda_version"] == "11.2"
    assert facts["os_distro"] == "ubuntu20.04"


def test_no_from_yields_nothing():
    assert extract_from_text("Dockerfile", "# scratch\nRUN true\n") == []


def test_variable_base_image_is_skipped():
    text = "ARG BASE_IMAGE=python:3.9\nFROM " + chr(36) + "BASE_IMAGE\n"
    assert extract_from_text("Dockerfile", text) == []
