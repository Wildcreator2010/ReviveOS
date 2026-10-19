"""environment.yml extraction."""

from __future__ import annotations

from revive_core.archaeology.evidence import extract_from_text

ENV_YML = """name: demo
channels:
  - defaults
  - conda-forge
dependencies:
  - python=3.7
  - numpy=1.18
  - pip:
      - requests==2.20.0
"""


def test_conda_dependencies_and_python():
    facts = extract_from_text("environment.yml", ENV_YML)[0].facts
    assert facts["python_requires"] == "3.7"
    assert facts["conda_env_name"] == "demo"
    assert facts["channels"] == ["defaults", "conda-forge"]
    deps = {dep["name"]: dep["version"] for dep in facts["dependencies"]}
    assert deps["numpy"] == "1.18"
    assert deps["requests"] == "2.20.0"


def test_conda_space_form_version():
    text = "dependencies:\n  - python 3.9.7\n  - scipy 1.7\n"
    facts = extract_from_text("environment.yml", text)[0].facts
    assert facts["python_requires"] == "3.9"
    deps = {dep["name"]: dep["version"] for dep in facts["dependencies"]}
    assert deps["scipy"] == "1.7"


def test_conda_invalid_yaml_is_a_warning():
    items = extract_from_text("environment.yml", "dependencies: [\n  - python=3.7\n")
    assert items and items[0].source_kind == "inference"


def test_conda_non_mapping_is_a_warning():
    items = extract_from_text("environment.yml", "- python=3.7\n")
    assert items and items[0].source_kind == "inference"
