"""README keyword extraction and lock-file extraction."""

from __future__ import annotations

from revive_core.archaeology.evidence import extract_from_text
from revive_core.archaeology.extractors import lockfile, readme


def test_readme_python_versions():
    text = "This project runs on Python 3.6 or Python 3.10 and above.\n"
    item = extract_from_text("README.md", text)[0]
    assert item.source_kind == "doc"
    assert item.facts["python_versions"] == ["3.6", "3.10"]


def test_readme_without_python_is_empty():
    assert extract_from_text("README.md", "# hello\n\nno runtime notes\n") == []


def test_readme_matches_readme_variants():
    assert readme.matches("README.md")
    assert readme.matches("README.rst")
    assert not readme.matches("readme_notes.txt")


def test_poetry_lock_packages():
    text = '[[package]]\nname = "numpy"\nversion = "1.16.0"\n\n[[package]]\nname = "requests"\nversion = "2.19.1"\n'
    item = extract_from_text("poetry.lock", text)[0]
    assert item.facts["lock"] is True
    deps = {dep["name"]: dep["version"] for dep in item.facts["dependencies"]}
    assert deps == {"numpy": "1.16.0", "requests": "2.19.1"}


def test_pipfile_lock_json():
    text = '{"default": {"flask": {"version": "==1.1.4"}}, "develop": {"pytest": {"version": "==7.4.0"}}}'
    item = extract_from_text("Pipfile.lock", text)[0]
    deps = {dep["name"]: dep["version"] for dep in item.facts["dependencies"]}
    assert deps == {"flask": "1.1.4", "pytest": "7.4.0"}


def test_requirements_lock_text():
    item = extract_from_text("requirements.lock", "Django==2.0.5\nrequests==2.19.1\n")[0]
    assert item.facts["lock"] is True
    assert {dep["name"] for dep in item.facts["dependencies"]} == {"django", "requests"}


def test_lock_matcher():
    assert lockfile.matches("poetry.lock")
    assert lockfile.matches("uv.lock")
    assert lockfile.matches("requirements-prod.lock")
    assert not lockfile.matches("requirements.txt")
