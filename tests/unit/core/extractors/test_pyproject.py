"""pyproject.toml extraction: PEP 621 and a poetry subset."""

from __future__ import annotations

from revive_core.archaeology.evidence import extract_from_text

PEP621 = """[project]
name = "demo"
requires-python = ">=3.9"
dependencies = ["uvicorn==0.30.0", "fastapi[standard]>=0.111"]
classifiers = ["Programming Language :: Python :: 3.10"]

[project.optional-dependencies]
test = ["pytest==7.4.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""

POETRY = """[tool.poetry]
name = "demo"

[tool.poetry.dependencies]
python = "^3.8"
requests = "^2.31"
numpy = { version = "^1.26", markers = "python_version >= '3.9'" }

[tool.poetry.group.dev.dependencies]
pytest = "==7.4.0"

[tool.poetry.dev-dependencies]
black = "^24.0"
"""


def test_pep621_project_table():
    items = extract_from_text("pyproject.toml", PEP621)
    facts = items[0].facts
    assert facts["python_requires"] == "3.9"
    assert facts["python_classifiers"] == ["3.10"]
    assert facts["build_backend"] == "hatchling.build"
    deps = {dep["name"]: dep for dep in facts["dependencies"]}
    assert deps["uvicorn"]["version"] == "0.30.0"
    assert deps["fastapi"]["extras"] == ["standard"]
    assert facts["extras_require"]["test"][0]["name"] == "pytest"


def test_poetry_dependencies_and_groups():
    items = extract_from_text("pyproject.toml", POETRY)
    facts = items[0].facts
    assert facts["python_requires"] == "3.8"
    names = {dep["name"] for dep in facts["dependencies"]}
    assert {"requests", "numpy", "pytest", "black"} <= names
    numpy = next(dep for dep in facts["dependencies"] if dep["name"] == "numpy")
    assert numpy["markers"] == "python_version >= '3.9'"


def test_poetry_python_spec_without_caret():
    text = '[tool.poetry.dependencies]\npython = ">=3.10"\n'
    facts = extract_from_text("pyproject.toml", text)[0].facts
    assert facts["python_requires"] == "3.10"


def test_invalid_toml_is_a_warning():
    items = extract_from_text("pyproject.toml", "[project\nname = 'x'\n")
    assert items and items[0].source_kind == "inference"
    assert "could not be parsed" in (items[0].note or "")
