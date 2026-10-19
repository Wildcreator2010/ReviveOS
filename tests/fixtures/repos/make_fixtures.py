#!/usr/bin/env python
"""Generate the golden fixture repositories with a reproducible git history.

Every repository is rebuilt from scratch using fixed author and committer dates,
so object hashes are stable across machines. Set REVIVE_GIT_BIN when git is not
on PATH (the coordinator installs a portable git under .tools/git).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUTHOR_NAME = "ReviveOS Fixture"
AUTHOR_EMAIL = "fixture@reviveos.dev"


def find_git() -> str:
    explicit = os.environ.get("REVIVE_GIT_BIN")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("git")
    if found:
        return found
    for parent in HERE.parents:
        for relative in ("cmd/git.exe", "bin/git", "bin/git.exe"):
            candidate = parent / ".tools" / "git" / relative
            if candidate.is_file():
                return str(candidate)
    raise SystemExit("git not found: set REVIVE_GIT_BIN to the git executable")


GIT = find_git()


def run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [GIT, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=True,
    )


def commit(repo: Path, *, date: str, message: str, files: dict[str, str], tags: tuple[str, ...] = ()) -> None:
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    run(["-C", str(repo), "add", "-A"])
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
    )
    run(["-C", str(repo), "commit", "-q", "-m", message], env=env)
    for tag in tags:
        run(["-C", str(repo), "tag", tag])


def build(name: str, commits: list[dict], *, force: bool = False) -> Path:
    repo = HERE / name
    if repo.exists() and force:
        shutil.rmtree(repo)
    if (repo / ".git").exists():
        print(f"skip {name} (already generated)")
        return repo
    repo.mkdir(parents=True, exist_ok=True)
    run(["init", "-q", "-b", "main", str(repo)])
    for spec in commits:
        commit(repo, **spec)
    print(f"built {name}: {len(commits)} commits")
    return repo


PY27_SETUP_EARLY = """from setuptools import setup

setup(
    name="legacy-flask-service",
    version="0.1.0",
    python_requires=">=2.7,<3",
    install_requires=[
        "Flask==0.10.1",
        "Jinja2==2.7.3",
        "Werkzeug==0.10.4",
    ],
    classifiers=[
        "Programming Language :: Python :: 2.7",
    ],
)
"""

PY27_SETUP_LATE = """from setuptools import setup

setup(
    name="legacy-flask-service",
    version="0.2.0",
    python_requires=">=2.7,<3",
    install_requires=[
        "Flask==0.12.2",
        "Jinja2==2.10",
        "Werkzeug==0.16.1",
    ],
    classifiers=[
        "Programming Language :: Python :: 2.7",
    ],
)
"""

PY27_REQ_EARLY = """Flask==0.10.1
Jinja2==2.7.3
Werkzeug==0.10.4
"""

PY27_REQ_LATE = """Flask==0.12.2
Jinja2==2.10
Werkzeug==0.16.1
MarkupSafe==1.0
"""

PY27_APP = """from flask import Flask

app = Flask(__name__)


@app.route("/")
def index():
    return "legacy"
"""

PY27_DOCKER = """FROM python:2.7-slim

WORKDIR /srv
COPY . /srv
RUN pip install -r requirements.txt
CMD ["python", "app.py"]
"""


def py27_flask() -> list[dict]:
    return [
        {
            "date": "2015-04-10T10:00:00+00:00",
            "message": "initial py2 flask service",
            "files": {
                "setup.py": PY27_SETUP_EARLY,
                "requirements.txt": PY27_REQ_EARLY,
                "app.py": PY27_APP,
                "README.md": "# Legacy Flask Service\n\nRuns on Python 2.7 only.\n",
            },
            "tags": ("v0.1.0",),
        },
        {
            "date": "2015-09-01T09:30:00+00:00",
            "message": "bump werkzeug",
            "files": {
                "requirements.txt": "Flask==0.10.1\nJinja2==2.7.3\nWerkzeug==0.11.0\n",
            },
        },
        {
            "date": "2016-05-20T14:15:00+00:00",
            "message": "pin final flask 0.12 line",
            "files": {
                "setup.py": PY27_SETUP_LATE,
                "requirements.txt": PY27_REQ_LATE,
                "Dockerfile": PY27_DOCKER,
            },
            "tags": ("v0.2.0",),
        },
    ]


def three_era_deps() -> list[dict]:
    return [
        {
            "date": "2015-06-01T08:00:00+00:00",
            "message": "2015 era dependencies",
            "files": {
                "requirements.txt": "Django==1.8.2\nrequests==2.7.0\n",
                "README.md": "# three-era-deps\n\nSame requirements file, three eras.\n",
            },
            "tags": ("v1.0",),
        },
        {
            "date": "2018-06-15T12:00:00+00:00",
            "message": "2018 era dependencies",
            "files": {
                "requirements.txt": "Django==2.0.5\nrequests==2.19.1\n",
            },
            "tags": ("v2.0",),
        },
        {
            "date": "2021-03-10T16:45:00+00:00",
            "message": "2021 era dependencies",
            "files": {
                "requirements.txt": "Django==3.2.5\nrequests==2.26.0\n",
            },
            "tags": ("v3.0",),
        },
    ]


HEALTHY_PYPROJECT = """[project]
name = "healthy-baseline"
version = "1.1.0"
description = "A healthy modern project used as the control fixture"
requires-python = ">=3.11"
dependencies = [
  "fastapi==0.111.0",
  "uvicorn==0.30.0",
]
classifiers = [
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
]
"""

HEALTHY_CI = """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
"""

HEALTHY_DOCKER = """FROM python:3.11-slim

WORKDIR /srv
COPY . /srv
RUN pip install .
CMD ["python", "-m", "healthy"]
"""


def healthy_baseline() -> list[dict]:
    return [
        {
            "date": "2024-01-10T09:00:00+00:00",
            "message": "initial healthy project",
            "files": {
                "pyproject.toml": HEALTHY_PYPROJECT,
                ".github/workflows/ci.yml": HEALTHY_CI,
                "Dockerfile": HEALTHY_DOCKER,
                "README.md": "# healthy-baseline\n\nRequires Python 3.11.\n",
                "healthy/__init__.py": "",
            },
            "tags": ("v1.0.0",),
        },
        {
            "date": "2024-03-01T11:00:00+00:00",
            "message": "bump fastapi",
            "files": {
                "pyproject.toml": HEALTHY_PYPROJECT.replace("fastapi==0.111.0", "fastapi==0.111.1"),
            },
        },
        {
            "date": "2024-05-01T15:30:00+00:00",
            "message": "add runtime module",
            "files": {
                "healthy/__main__.py": "print('healthy')\n",
            },
            "tags": ("v1.1.0",),
        },
    ]


AMBIGUOUS_SETUP = """from setuptools import setup

setup(
    name="ambiguous-readme",
    version="0.3.0",
    install_requires=["requests>=2.0"],
    classifiers=[
        "Programming Language :: Python :: 3",
    ],
)
"""


def ambiguous_readme() -> list[dict]:
    return [
        {
            "date": "2019-07-01T10:00:00+00:00",
            "message": "initial ambiguous project",
            "files": {
                "setup.py": AMBIGUOUS_SETUP,
                "requirements.txt": "requests\n",
                "README.md": "# ambiguous-readme\n\nThis project runs on Python 3.6 or Python 3.10 and above.\n",
            },
            "tags": ("v0.1.0",),
        },
        {
            "date": "2020-02-14T13:20:00+00:00",
            "message": "document ambiguous support",
            "files": {
                "README.md": "# ambiguous-readme\n\nLegacy users run Python 3.6; new users run Python 3.10 and above.\n",  # noqa: E501
            },
        },
        {
            "date": "2021-11-30T17:05:00+00:00",
            "message": "loosen requests",
            "files": {
                "requirements.txt": "requests>=2.0\n",
            },
            "tags": ("v0.3.0",),
        },
    ]


MODERN_PYPROJECT = """[project]
name = "modern-uvicorn"
version = "2.0.0"
description = "Modern golden path fixture"
requires-python = ">=3.9"
dependencies = [
  "uvicorn==0.30.0",
  "fastapi==0.111.0",
]
classifiers = [
  "Programming Language :: Python :: 3.9",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""

MODERN_CI = """ + JSON.stringify(ciModern) + """


def modern_uvicorn() -> list[dict]:
    return [
        {
            "date": "2023-02-01T08:30:00+00:00",
            "message": "initial modern service",
            "files": {
                "pyproject.toml": MODERN_PYPROJECT,
                ".github/workflows/ci.yml": MODERN_CI,
                "Dockerfile": "FROM python:3.9-slim\n\nWORKDIR /srv\nCOPY . /srv\n",
                "README.md": "# modern-uvicorn\n\nRequires Python 3.9 or newer.\n",
                "service/__init__.py": "",
            },
            "tags": ("v1.0.0",),
        },
        {
            "date": "2023-08-15T12:00:00+00:00",
            "message": "bump uvicorn",
            "files": {
                "pyproject.toml": MODERN_PYPROJECT.replace("uvicorn==0.30.0", "uvicorn==0.30.1"),
            },
        },
        {
            "date": "2024-06-20T18:45:00+00:00",
            "message": "add service entrypoint",
            "files": {
                "service/main.py": "def main():\n    return 0\n",
            },
            "tags": ("v2.0.0",),
        },
    ]


COLLECTIONS_SETUP = """from setuptools import setup

setup(
    name="collections-abc",
    version="1.0.0",
    python_requires=">=3.9,<3.10",
    install_requires=["requests==2.31.0"],
    classifiers=[
        "Programming Language :: Python :: 3.9",
    ],
)
"""

COLLECTIONS_LEGACY = """from collections import Iterable


def walk(value):
    return isinstance(value, Iterable)
"""


def collections_abc() -> list[dict]:
    return [
        {
            "date": "2022-04-01T09:10:00+00:00",
            "message": "initial collections usage",
            "files": {
                "setup.py": COLLECTIONS_SETUP,
                "requirements.txt": "requests==2.31.0\n",
                "legacy/__init__.py": COLLECTIONS_LEGACY,
                "README.md": "# collections-abc\n\nTargets Python 3.9.\n",
            },
            "tags": ("v1.0.0",),
        },
        {
            "date": "2022-09-12T14:40:00+00:00",
            "message": "add helper",
            "files": {
                "legacy/helpers.py": "def noop():\n    return None\n",
            },
        },
        {
            "date": "2023-05-30T11:25:00+00:00",
            "message": "pin requests and add urllib3",
            "files": {
                "requirements.txt": "requests==2.31.0\nurllib3==2.0.7\n",
            },
            "tags": ("v1.1.0",),
        },
    ]


REPOS = {
    "py27-flask": py27_flask,
    "three-era-deps": three_era_deps,
    "healthy-baseline": healthy_baseline,
    "ambiguous-readme": ambiguous_readme,
    "modern-uvicorn": modern_uvicorn,
    "collections-abc": collections_abc,
}


def main() -> int:
    force = "--force" in sys.argv
    for name, factory in REPOS.items():
        build(name, factory(), force=force)
    print("fixtures ready in", HERE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
