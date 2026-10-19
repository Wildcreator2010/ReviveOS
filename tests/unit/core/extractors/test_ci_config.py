"""CI configuration extraction: GitHub Actions, Travis, tox."""

from __future__ import annotations

from revive_core.archaeology.evidence import extract_from_text
from revive_core.archaeology.extractors import ci_config

WORKFLOW = """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11"]
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.9"
"""

WORKFLOW_UNQUOTED = """jobs:
  test:
    strategy:
      matrix:
        python-version: [3.8, 3.10]
"""


def test_matches_known_ci_files():
    assert ci_config.matches(".github/workflows/ci.yml")
    assert ci_config.matches(".github/workflows/release.yaml")
    assert ci_config.matches(".travis.yml")
    assert ci_config.matches("tox.ini")
    assert not ci_config.matches("config/settings.yml")


def test_github_actions_matrix():
    facts = extract_from_text(".github/workflows/ci.yml", WORKFLOW)[0].facts
    assert facts["python_versions"] == ["3.9", "3.10", "3.11"]
    assert facts["ci_system"] == "github-actions"


def test_github_actions_recovers_float_folded_310():
    facts = extract_from_text(".github/workflows/ci.yml", WORKFLOW_UNQUOTED)[0].facts
    assert "3.10" in facts["python_versions"]
    assert "3.8" in facts["python_versions"]


def test_travis_python_list():
    text = 'python:\n  - "2.7"\n  - "3.6"\n'
    facts = extract_from_text(".travis.yml", text)[0].facts
    assert facts["python_versions"] == ["2.7", "3.6"]
    assert facts["ci_system"] == "travis"


def test_tox_envlist():
    text = "[tox]\nenvlist = py27, py310, py311\n"
    facts = extract_from_text("tox.ini", text)[0].facts
    assert facts["python_versions"] == ["2.7", "3.10", "3.11"]
    assert facts["envlist"] == ["py27", "py310", "py311"]


def test_invalid_workflow_yaml_is_a_warning():
    items = extract_from_text(".github/workflows/ci.yml", "jobs: [\n")
    assert items and items[0].source_kind == "inference"
