"""requirements*.txt extraction: pins, ranges, extras, markers, -r expansion."""

from __future__ import annotations

from revive_core.archaeology.evidence import ExtractContext, extract_from_text
from revive_core.archaeology.extractors import requirements


def run(text: str, reader=None):
    return extract_from_text("requirements.txt", text, ExtractContext(read_file=reader))


def test_matches_only_requirements_txt():
    assert requirements.matches("requirements.txt")
    assert requirements.matches("requirements-dev.txt")
    assert requirements.matches("nested/requirements_test.txt")
    assert not requirements.matches("constraints.txt")
    assert not requirements.matches("requirements.lock")


def test_pinned_ranges_extras_and_markers():
    text = 'Flask==0.12.2\nrequests[security]>=2.0 ; python_version < "3.8"\nurllib3\n# comment\n'
    items = run(text)
    manifest = [item for item in items if item.facts.get("dependencies")]
    assert len(manifest) == 1
    deps = {dep["name"]: dep for dep in manifest[0].facts["dependencies"]}
    assert deps["flask"]["version"] == "0.12.2"
    assert deps["flask"]["pinned"] is True
    assert deps["requests"]["extras"] == ["security"]
    assert deps["requests"]["version"] == ""
    assert deps["requests"]["pinned"] is False
    assert 'python_version < "3.8"' in deps["requests"]["markers"]
    assert deps["urllib3"]["version"] == ""


def test_dash_r_expands_exactly_one_level():
    text = "Flask==0.12.2\n-r requirements-dev.txt\n"
    child = "pytest==4.6.0\n"
    items = run(text, reader=lambda rel: child if rel == "requirements-dev.txt" else None)
    parent = next(
        item for item in items if item.reference.file == "requirements.txt" and item.facts.get("dependencies")
    )
    assert parent.facts["requirements_includes"] == ["requirements-dev.txt"]
    included = next(item for item in items if item.reference.file == "requirements-dev.txt")
    assert included.facts["dependencies"][0]["name"] == "pytest"
    assert "included from requirements.txt" in (included.note or "")


def test_nested_include_is_ignored_with_warning():
    text = "-r requirements-dev.txt\n"
    child = "-r requirements-extra.txt\n"
    items = run(text, reader=lambda rel: child if rel == "requirements-dev.txt" else "x==1.0\n")
    warnings = [item for item in items if item.source_kind == "inference"]
    assert any("one level" in (item.note or "") for item in warnings)


def test_missing_include_warns_without_raising():
    items = run("-r missing.txt\n", reader=lambda rel: None)
    warnings = [item for item in items if item.source_kind == "inference"]
    assert warnings and "not found" in (warnings[0].note or "")


def test_unparseable_line_downgrades_to_warning():
    items = run("Flask==0.12.2\n!!!not a requirement!!!\n")
    assert any(item.facts.get("dependencies") for item in items)
    assert any(item.source_kind == "inference" and "unparseable" in (item.note or "") for item in items)


def test_line_continuations_are_joined():
    text = "requests==2.19.1 " + chr(92) + "\n    --hash=sha256:deadbeef\n"
    items = run(text)
    deps = items[0].facts["dependencies"]
    assert deps[0]["name"] == "requests"
    assert deps[0]["version"] == "2.19.1"
