"""Historic runtime image matrix and image planner (T-SB-01).

The matrix is data: a single MATRIX constant describes which Ubuntu release
carries which Python and through which install channel.  There is no if/else
ladder anywhere else in the code base.  plan_image resolves a genome to an
ImagePlan, or to Unsupported with the three closest candidates so a
human/agent can decide.

Digest honesty
--------------
Resolving a tag such as ubuntu:18.04 to a sha256 repo digest requires a
registry round trip (docker manifest inspect).  That is impossible in this
offline/CI sandbox, so rows carry digest=None together with
digest_expected=True: the plan asks for a pinned digest and resolve_digest()
fills it when a registry is reachable.  No digest is ever fabricated.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

PythonInstall = Literal["apt", "conda", "source"]
Channel = Literal["apt", "deadsnakes", "conda", "source"]

#: Only registries that the sandbox egress whitelist already trusts.
PYPI_INDEX_URL = "https://pypi.org/simple"
CONDA_CHANNEL_URL = "https://repo.anaconda.com/pkgs/main"

_OS_RE = re.compile(r"(\d{2})\.(\d{2})")
_PY_RE = re.compile(r"(\d+)\.(\d+)")


@dataclass(frozen=True)
class PythonSpec:
    """How one Python version is provisioned inside one OS row."""

    version: str
    install: PythonInstall
    channel: Channel
    extra_apt: tuple[str, ...] = ()
    conda_channels: tuple[str, ...] = ()
    conda_env_yaml: str | None = None
    note: str = ""
    template: str = ""


@dataclass(frozen=True)
class MatrixRow:
    """One Ubuntu release plus every Python it can host."""

    os_release: str
    os_image: str
    pythons: Mapping[str, PythonSpec]
    digest: str | None = None
    digest_expected: bool = True
    template: str = ""
    note: str = ""

    def spec(self, python_version: str) -> PythonSpec | None:
        return self.pythons.get(python_version)


def _spec(
    version: str,
    install: PythonInstall,
    channel: Channel,
    *,
    extra_apt: tuple[str, ...] = (),
    conda_channels: tuple[str, ...] = (),
    conda_env_yaml: str | None = None,
    note: str = "",
    template: str = "",
) -> PythonSpec:
    return PythonSpec(
        version=version,
        install=install,
        channel=channel,
        extra_apt=extra_apt,
        conda_channels=conda_channels,
        conda_env_yaml=conda_env_yaml,
        note=note,
        template=template,
    )


# Common apt build tooling shared by the source-compile channel.
_SOURCE_BUILD_APT = (
    "build-essential",
    "ca-certificates",
    "curl",
    "libbz2-dev",
    "libffi-dev",
    "libncurses5-dev",
    "libreadline-dev",
    "libsqlite3-dev",
    "libssl-dev",
    "wget",
    "zlib1g-dev",
)

_DEADSNAKES_APT = ("software-properties-common", "ca-certificates")

_CONDA_APT = ("bzip2", "ca-certificates", "curl")

_CONDA_ENV_YAML = """name: revive
channels:
  - {{ conda_channel_url }}
dependencies:
  - python={{ python_version }}
"""


# --------------------------------------------------------------------------
# THE MATRIX.  Data, not control flow.  Golden paths are annotated.
# --------------------------------------------------------------------------
MATRIX: tuple[MatrixRow, ...] = (
    MatrixRow(
        os_release="22.04",
        os_image="ubuntu:22.04",
        template="base-py3.10.Dockerfile.tpl",
        note="Ubuntu 22.04 default interpreter, apt channel.",
        pythons={
            "3.10": _spec("3.10", "apt", "apt", extra_apt=("python3.10", "python3.10-venv", "python3-pip")),
            "3.9": _spec("3.9", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
            "3.11": _spec("3.11", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
            "3.12": _spec("3.12", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
        },
    ),
    MatrixRow(
        os_release="20.04",
        os_image="ubuntu:20.04",
        template="base-py3.8.Dockerfile.tpl",
        note="Ubuntu 20.04 default interpreter, apt channel.",
        pythons={
            "3.8": _spec("3.8", "apt", "apt", extra_apt=("python3.8", "python3.8-venv", "python3-pip")),
            "3.6": _spec("3.6", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
            "3.7": _spec("3.7", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
            "3.9": _spec("3.9", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
        },
    ),
    MatrixRow(
        os_release="18.04",
        os_image="ubuntu:18.04",
        template="base-py3.6.Dockerfile.tpl",
        note="Golden path: Ubuntu 18.04 + Python 3.6 via deadsnakes.",
        pythons={
            # GOLDEN PATH 2 - deadsnakes PPA.
            "3.6": _spec("3.6", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
            "3.5": _spec("3.5", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
            "3.7": _spec("3.7", "apt", "deadsnakes", extra_apt=_DEADSNAKES_APT),
            # GOLDEN PATH 1 - Python 2.7 through conda.
            "2.7": _spec(
                "2.7",
                "conda",
                "conda",
                extra_apt=_CONDA_APT,
                conda_channels=(CONDA_CHANNEL_URL,),
                conda_env_yaml=_CONDA_ENV_YAML,
                note="Golden path: Python 2.7 is only reachable through conda.",
            ),
        },
    ),
    MatrixRow(
        os_release="16.04",
        os_image="ubuntu:16.04",
        template="base-py2.7.Dockerfile.tpl",
        note="Ubuntu 16.04: source compile for 3.5, conda for 2.7.",
        pythons={
            "3.5": _spec("3.5", "source", "source", extra_apt=_SOURCE_BUILD_APT),
            "3.4": _spec("3.4", "source", "source", extra_apt=_SOURCE_BUILD_APT),
            "2.7": _spec(
                "2.7",
                "conda",
                "conda",
                extra_apt=_CONDA_APT,
                conda_channels=(CONDA_CHANNEL_URL,),
                conda_env_yaml=_CONDA_ENV_YAML,
            ),
        },
    ),
    MatrixRow(
        os_release="14.04",
        os_image="ubuntu:14.04",
        template="base-py3.4.Dockerfile.tpl",
        note="Golden path: Ubuntu 14.04 + Python 3.4 compiled from source.",
        pythons={
            # GOLDEN PATH 3 - source compile.
            "3.4": _spec(
                "3.4",
                "source",
                "source",
                extra_apt=_SOURCE_BUILD_APT,
                note="Golden path: no distro package exists, compile CPython 3.4.",
            ),
            "3.5": _spec("3.5", "source", "source", extra_apt=_SOURCE_BUILD_APT),
            "2.7": _spec(
                "2.7",
                "conda",
                "conda",
                extra_apt=_CONDA_APT,
                conda_channels=(CONDA_CHANNEL_URL,),
                conda_env_yaml=_CONDA_ENV_YAML,
            ),
        },
    ),
)

#: When the genome only names a Python version we pick the newest OS that can
#: host it (fewest surprises for pip wheels).
DEFAULT_OS_FOR_PYTHON: Mapping[str, str] = {
    "2.7": "18.04",
    "3.4": "14.04",
    "3.5": "18.04",
    "3.6": "18.04",
    "3.7": "20.04",
    "3.8": "20.04",
    "3.9": "22.04",
    "3.10": "22.04",
    "3.11": "22.04",
    "3.12": "22.04",
}


@dataclass(frozen=True)
class ImagePlan:
    """Resolved build recipe for one genome."""

    os_image: str
    os_release: str
    os_digest: str | None
    digest_expected: bool
    python_version: str
    python_install: PythonInstall
    channel: Channel
    extra_apt: tuple[str, ...]
    conda_env_yaml: str | None
    conda_channels: tuple[str, ...]
    template: str
    pip_index_url: str = PYPI_INDEX_URL
    note: str = ""

    @property
    def os_reference(self) -> str:
        """ubuntu:18.04, optionally pinned by digest."""

        return f"{self.os_image}@{self.os_digest}" if self.os_digest else self.os_image

    def to_dict(self) -> dict[str, Any]:
        return {
            "os_image": self.os_image,
            "os_release": self.os_release,
            "os_digest": self.os_digest,
            "digest_expected": self.digest_expected,
            "python_version": self.python_version,
            "python_install": self.python_install,
            "channel": self.channel,
            "extra_apt": list(self.extra_apt),
            "conda_env_yaml": self.conda_env_yaml,
            "conda_channels": list(self.conda_channels),
            "template": self.template,
            "pip_index_url": self.pip_index_url,
            "note": self.note,
        }


@dataclass(frozen=True)
class Unsupported:
    """No matrix row matched; carry the closest candidates for a decision."""

    requested_os: str | None
    requested_python: str | None
    candidates: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_os": self.requested_os,
            "requested_python": self.requested_python,
            "candidates": list(self.candidates),
            "reason": self.reason,
        }


# --------------------------------------------------------------------------
# Parsing genome input.
# --------------------------------------------------------------------------
def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("version", "image"):
            found = _as_text(value.get(key))
            if found:
                return found
        return None
    text = str(value).strip()
    return text or None


def parse_os_release(value: Any) -> str | None:
    """Return 18.04 from many shapes (ubuntu:18.04, Ubuntu 18.04)."""

    text = _as_text(value)
    if not text:
        return None
    match = _OS_RE.search(text)
    if not match:
        return None
    return f"{match.group(1)}.{match.group(2)}"


def parse_python_version(value: Any) -> str | None:
    text = _as_text(value)
    if not text:
        return None
    match = _PY_RE.search(text)
    if not match:
        return None
    return f"{int(match.group(1))}.{int(match.group(2))}"


def _genome_fields(genome: Any) -> tuple[str | None, str | None]:
    """Extract (os_release, python_version) from a genome-like object or mapping."""

    if genome is None:
        return None, None
    if isinstance(genome, Mapping):
        os_value = genome.get("os")
        py_value = genome.get("python")
    else:
        os_value = getattr(genome, "os", None)
        py_value = getattr(genome, "python", None)
    os_release = parse_os_release(os_value)
    python_version = parse_python_version(py_value)
    return os_release, python_version


# --------------------------------------------------------------------------
# Planning.
# --------------------------------------------------------------------------
def _row(os_release: str) -> MatrixRow | None:
    for row in MATRIX:
        if row.os_release == os_release:
            return row
    return None


def _py_key(version: str) -> tuple[int, int]:
    match = _PY_RE.match(version)
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def nearest_candidates(os_release: str | None, python_version: str | None, limit: int = 3) -> tuple[str, ...]:
    """Rank matrix cells by distance to the request and return labels."""

    target_py = _py_key(python_version) if python_version else None
    scored: list[tuple[float, str]] = []
    for row in MATRIX:
        try:
            os_distance = 0.0 if os_release is None or row.os_release == os_release else 1.0
            if os_release and row.os_release != os_release:
                os_distance = abs(float(row.os_release) - float(os_release))
        except ValueError:  # pragma: no cover - defensive
            os_distance = 1.0
        for py, spec in row.pythons.items():
            if target_py is None:
                py_distance = 0.0
            else:
                py_distance = abs((_py_key(py)[0] * 100 + _py_key(py)[1]) - (target_py[0] * 100 + target_py[1]))
            score = os_distance * 10.0 + py_distance
            scored.append((score, f"ubuntu{row.os_release}+python{py}({spec.channel})"))
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple(label for _, label in scored[:limit])


def plan_image(genome: Any, *, prefer_os: str | None = None) -> ImagePlan | Unsupported:
    """Resolve a genome to an ImagePlan or an Unsupported.

    prefer_os lets a caller force an OS release (used by tests and by the
    archaeology layer when the repository pins a CI image).
    """

    requested_os, python_version = _genome_fields(genome)
    if prefer_os:
        requested_os = parse_os_release(prefer_os) or requested_os

    if not python_version:
        return Unsupported(
            requested_os=requested_os,
            requested_python=None,
            candidates=nearest_candidates(requested_os, None),
            reason="genome does not pin a Python version, so no historic image can be selected",
        )

    if requested_os is None:
        requested_os = DEFAULT_OS_FOR_PYTHON.get(python_version)

    row = _row(requested_os) if requested_os else None
    spec = row.spec(python_version) if row else None

    if spec is None and requested_os is not None:
        # Fall back to the default OS for that Python before declaring defeat.
        fallback_os = DEFAULT_OS_FOR_PYTHON.get(python_version)
        if fallback_os and fallback_os != requested_os:
            fallback_row = _row(fallback_os)
            fallback_spec = fallback_row.spec(python_version) if fallback_row else None
            if fallback_spec is not None:
                row, spec = fallback_row, fallback_spec

    if row is None or spec is None:
        return Unsupported(
            requested_os=requested_os,
            requested_python=python_version,
            candidates=nearest_candidates(requested_os, python_version),
            reason=(
                f"no matrix cell for os={requested_os!r} python={python_version!r}; "
                "the closest supported combinations are listed in candidates"
            ),
        )

    return ImagePlan(
        os_image=row.os_image,
        os_release=row.os_release,
        os_digest=row.digest,
        digest_expected=row.digest_expected,
        python_version=spec.version,
        python_install=spec.install,
        channel=spec.channel,
        extra_apt=spec.extra_apt,
        conda_env_yaml=spec.conda_env_yaml,
        conda_channels=spec.conda_channels,
        # The template is keyed by Python version, never by the OS row: an OS
        # row can host several install channels (18.04 hosts both deadsnakes
        # 3.6 and conda 2.7), so the row-level template is only a fallback.
        template=spec.template or f"base-py{spec.version}.Dockerfile.tpl",
        note=spec.note or row.note,
    )


def resolve_digest(reference: str, *, docker_bin: str = "docker") -> str | None:
    """Resolve ubuntu:18.04 to sha256:... via the docker CLI.

    Requires a reachable Docker/registry (integration tests mark this
    requires_docker).  Returns None when it cannot be resolved instead of
    inventing a digest.
    """

    import shutil
    import subprocess

    exe = shutil.which(docker_bin) or docker_bin
    try:
        proc = subprocess.run(
            [exe, "manifest", "inspect", "--verbose", reference],
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r'"digest"\s*:\s*"(sha256:[0-9a-f]{64})"', proc.stdout)
    return match.group(1) if match else None


__all__ = [
    "Channel",
    "PythonInstall",
    "PythonSpec",
    "MatrixRow",
    "MATRIX",
    "DEFAULT_OS_FOR_PYTHON",
    "ImagePlan",
    "Unsupported",
    "plan_image",
    "parse_os_release",
    "parse_python_version",
    "nearest_candidates",
    "resolve_digest",
    "PYPI_INDEX_URL",
    "CONDA_CHANNEL_URL",
]
