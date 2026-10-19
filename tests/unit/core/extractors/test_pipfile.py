"""Pipfile extraction."""

from __future__ import annotations

from revive_core.archaeology.evidence import extract_from_text

PIPFILE = """[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
flask = "==1.1.4"
requests = { version = ">=2.20", markers = "python_version >= '3.6'" }

[dev-packages]
pytest = "*"

[requires]
python_version = "3.6"
"""


def test_pipfile_packages_and_requires():
    facts = extract_from_text("Pipfile", PIPFILE)[0].facts
    assert facts["python_requires"] == "3.6"
    deps = {dep["name"]: dep for dep in facts["dependencies"]}
    assert deps["flask"]["version"] == "1.1.4"
    assert deps["requests"]["version"] == ""
    assert deps["pytest"]["name"] == "pytest"


def test_pipfile_python_full_version_wins():
    text = '[requires]\npython_full_version = "3.10.4"\npython_version = "3.10"\n'
    facts = extract_from_text("Pipfile", text)[0].facts
    assert facts["python_requires"] == "3.10"


def test_pipfile_invalid_toml_is_a_warning():
    items = extract_from_text("Pipfile", '[packages\nflask = "1.0"\n')
    assert items and items[0].source_kind == "inference"
