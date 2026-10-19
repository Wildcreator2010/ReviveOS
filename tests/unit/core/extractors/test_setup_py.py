"""setup.py (AST only) and setup.cfg extraction."""

from __future__ import annotations

from revive_core.archaeology.evidence import extract_from_text

SETUP_PY = """from setuptools import setup

setup(
    name="demo",
    python_requires=">=2.7,<3",
    install_requires=["Flask==0.12.2", "Jinja2==2.10"],
    classifiers=["Programming Language :: Python :: 2.7"],
)
"""

SETUP_CFG = """[metadata]
name = demo
classifiers =
    Programming Language :: Python :: 3.8
    Programming Language :: Python :: 3.9

[options]
python_requires = >=3.8,<4
install_requires =
    requests==2.31.0
    urllib3>=2.0

[options.extras_require]
test =
    pytest==7.4.0
"""


def test_setup_py_normalizes_python_requires():
    items = extract_from_text("setup.py", SETUP_PY)
    facts = items[0].facts
    assert facts["python_requires"] == "2.7"
    assert facts["python_requires_raw"] == ">=2.7,<3"
    assert facts["python_classifiers"] == ["2.7"]
    deps = {dep["name"]: dep["version"] for dep in facts["dependencies"]}
    assert deps == {"flask": "0.12.2", "jinja2": "2.10"}


def test_setup_py_non_literal_argument_is_skipped_with_warning():
    text = "from setuptools import setup\nREQS = ['x']\nsetup(name='demo', install_requires=REQS, python_requires=os.environ['X'])\n"  # noqa: E501
    items = extract_from_text("setup.py", text)
    assert any(item.source_kind == "inference" and "not a literal" in (item.note or "") for item in items)


def test_setup_py_syntax_error_is_a_warning():
    items = extract_from_text("setup.py", "def broken(:\n")
    assert len(items) == 1
    assert items[0].source_kind == "inference"
    assert "could not be parsed" in (items[0].note or "")


def test_setup_py_without_setup_call_is_ignored():
    assert extract_from_text("setup.py", "import os\nprint(os.getcwd())\n") == []


def test_setup_cfg_metadata_and_options():
    items = extract_from_text("setup.cfg", SETUP_CFG)
    facts = items[0].facts
    assert facts["python_requires"] == "3.8"
    assert facts["python_classifiers"] == ["3.8", "3.9"]
    deps = {dep["name"]: dep["version"] for dep in facts["dependencies"]}
    assert deps == {"requests": "2.31.0", "urllib3": ""}
    assert facts["extras_require"]["test"][0]["name"] == "pytest"


def test_setup_cfg_broken_file_is_a_warning():
    items = extract_from_text("setup.cfg", "[options\npython_requires = 3.8\n")
    assert items and items[0].source_kind == "inference"
