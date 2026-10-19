"""The walker that turns a tree into EvidenceItems."""

from __future__ import annotations

from pathlib import Path

from revive_core.archaeology.evidence import extract_evidence


def test_walker_finds_manifests_and_skips_noise(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("Flask==0.12.2\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup(python_requires='2.7')\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.9"\n', encoding="utf-8")
    noise = tmp_path / "node_modules" / "pkg"
    noise.mkdir(parents=True)
    (noise / "requirements.txt").write_text("bogus==1.0\n", encoding="utf-8")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "requirements.txt").write_text("bogus==2.0\n", encoding="utf-8")

    items = extract_evidence(tmp_path)
    files = {item.reference.file for item in items}
    assert "requirements.txt" in files
    assert "setup.py" in files
    assert "pyproject.toml" in files
    assert not any("node_modules" in path for path in files)
    assert not any(path.startswith(".git") for path in files)


def test_walker_reports_unreadable_file_as_warning(tmp_path: Path, monkeypatch):
    target = tmp_path / "requirements.txt"
    target.write_text("Flask==0.12.2\n", encoding="utf-8")
    original = Path.read_text

    def exploding_read(self, *args, **kwargs):
        if self.name == "requirements.txt":
            raise OSError("denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", exploding_read)
    items = extract_evidence(tmp_path)
    assert any(item.source_kind == "inference" and "could not read" in (item.note or "") for item in items)


def test_golden_py27_flask_evidence(golden_repos: Path):
    repo = golden_repos / "py27-flask"
    items = extract_evidence(repo)
    setup = next(item for item in items if item.reference.file == "setup.py")
    assert setup.facts["python_requires"] == "2.7"
    requirements = next(item for item in items if item.reference.file == "requirements.txt")
    deps = {dep["name"]: dep["version"] for dep in requirements.facts["dependencies"]}
    assert deps["flask"] == "0.12.2"
    docker = next(item for item in items if item.reference.file == "Dockerfile")
    assert docker.facts["base_image"] == "python:2.7-slim"
