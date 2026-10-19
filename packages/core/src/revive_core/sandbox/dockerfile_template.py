"""Jinja2 renderer for the historic base-image Dockerfiles (T-SB-01).

All interpolation goes through explicit, validated filters:

* shq        - shlex.quote + a strict charset check (packages, channels);
* pkgjoin    - validates every apt package token and joins with line breaks;
* imgref     - validates an image reference and optional sha256 digest.

The renderer refuses to return text containing the forbidden
"curl ... | sh" pattern, so a malicious genome can neither inject shell
metacharacters nor smuggle a remote-script-to-shell pipe into a Dockerfile.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from urllib.parse import urlparse

import jinja2

from .image_matrix import ImagePlan, Unsupported, plan_image

#: Official python.org source releases used by the source-compile channel.
SOURCE_RELEASE_PATCH: dict[str, str] = {
    "3.4": "10",
    "3.5": "10",
}

MINICONDA_URLS: dict[str, str] = {
    "2": "https://repo.anaconda.com/miniconda/Miniconda2-latest-Linux-x86_64.sh",
    "3": "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh",
}

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+:=-]*$")
#: Index/channel hosts a build may talk to (mirrors executor.ALLOWED_BUILD_DOMAINS).
_ALLOWED_URL_HOSTS = frozenset(
    {
        "pypi.org",
        "files.pythonhosted.org",
        "repo.anaconda.com",
    }
)
_SAFE_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/:@-]*$")
_SAFE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_VERSION = re.compile(r"^\d+\.\d+$")

FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"curl[^\n|]*\|[^\n]*\b(sh|bash)\b"),
    re.compile(r"wget[^\n|]*\|[^\n]*\b(sh|bash)\b"),
    re.compile(r"(?<!\S)(eval|source)\s+/dev/(stdin|tcp)"),
)


class DockerfileError(ValueError):
    """A plan or template produced an unsafe / malformed Dockerfile."""


def _workspace_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "infra" / "sandbox").is_dir():
            return parent
    # Fall back to a path relative to the package (tests pass template_dir).
    return Path(__file__).resolve().parents[4]


def default_template_dir() -> Path:
    return _workspace_root() / "infra" / "sandbox"


def _validate_token(value: str, *, what: str) -> str:
    text = str(value).strip()
    if not _SAFE_TOKEN.match(text):
        raise DockerfileError(f"unsafe {what}: {value!r}")
    return text


def shq(value: object) -> str:
    """Quote a shell word after rejecting dangerous characters outright."""

    return shlex.quote(_validate_token(str(value), what="shell token"))


def pkgjoin(values: object) -> str:
    """Validate and join apt package names; one per continued line."""

    items = values if isinstance(values, (list, tuple)) else []
    tokens = [str(item) for item in items]
    checked = [_validate_token(token, what="apt package") for token in tokens]
    if not checked:
        return ""
    return " \\\n    ".join(checked)


def urlv(value: object) -> str:
    """Validate an https index/channel URL against the egress allowlist."""

    text = str(value).strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _ALLOWED_URL_HOSTS:
        raise DockerfileError(
            f"index/channel url {text!r} is not https on an allowed host {sorted(_ALLOWED_URL_HOSTS)}"
        )
    return text


def urlq(value: object) -> str:
    return shlex.quote(urlv(value))


def imgref(image: str, digest: str | None) -> str:
    text = str(image).strip()
    if not _SAFE_IMAGE.match(text):
        raise DockerfileError(f"unsafe base image reference: {image!r}")
    if digest:
        if not _SAFE_DIGEST.match(str(digest)):
            raise DockerfileError(f"unsafe image digest: {digest!r}")
        return f"{text}@{digest}"
    return text


def build_context(plan: ImagePlan) -> dict[str, object]:
    if not _SAFE_VERSION.match(plan.python_version):
        raise DockerfileError(f"unsafe python version: {plan.python_version!r}")
    major = plan.python_version.split(".", 1)[0]
    source_patch = SOURCE_RELEASE_PATCH.get(plan.python_version, "0")
    context: dict[str, object] = {
        "os_image": plan.os_image,
        "os_release": plan.os_release,
        "os_digest": plan.os_digest,
        "os_reference": imgref(plan.os_image, plan.os_digest),
        "digest_expected": plan.digest_expected,
        "python_version": plan.python_version,
        "python_major": major,
        "python_install": plan.python_install,
        "channel": plan.channel,
        "extra_apt": list(plan.extra_apt),
        "pip_index_url": plan.pip_index_url,
        "conda_channels": list(plan.conda_channels),
        "conda_channel_url": (plan.conda_channels[0] if plan.conda_channels else ""),
        "conda_env_yaml": plan.conda_env_yaml or "",
        "miniconda_url": MINICONDA_URLS.get(major, MINICONDA_URLS["3"]),
        "source_release": f"{plan.python_version}.{source_patch}",
        "note": plan.note,
    }
    return context


def make_environment(template_dir: Path | None = None) -> jinja2.Environment:
    directory = Path(template_dir) if template_dir else default_template_dir()
    if not directory.is_dir():
        raise DockerfileError(f"template directory not found: {directory}")
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(directory)),
        undefined=jinja2.StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["shq"] = shq
    env.filters["pkgjoin"] = pkgjoin
    env.filters["imgref"] = imgref
    env.filters["urlv"] = urlv
    env.filters["urlq"] = urlq
    return env


def check_forbidden(text: str) -> None:
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            raise DockerfileError(f"generated Dockerfile matches forbidden pattern {pattern.pattern!r}")


def render_dockerfile(plan: ImagePlan, *, template_dir: Path | None = None) -> str:
    """Render the Dockerfile for one ImagePlan; raises DockerfileError if unsafe."""

    env = make_environment(template_dir)
    try:
        template = env.get_template(plan.template)
    except jinja2.TemplateNotFound as exc:
        raise DockerfileError(f"template not found: {plan.template}") from exc
    text = template.render(**build_context(plan))
    if "FROM " not in text.splitlines()[0] and not any(line.startswith("FROM ") for line in text.splitlines()):
        raise DockerfileError("rendered Dockerfile has no FROM instruction")
    check_forbidden(text)
    return text


def render_for_genome(
    genome: object, *, template_dir: Path | None = None, prefer_os: str | None = None
) -> tuple[str, ImagePlan]:
    """Convenience: genome -> (dockerfile text, plan)."""

    plan = plan_image(genome, prefer_os=prefer_os)
    if isinstance(plan, Unsupported):
        raise DockerfileError(f"unsupported environment: {plan.reason}")
    return render_dockerfile(plan, template_dir=template_dir), plan


__all__ = [
    "DockerfileError",
    "FORBIDDEN_PATTERNS",
    "SOURCE_RELEASE_PATCH",
    "MINICONDA_URLS",
    "default_template_dir",
    "make_environment",
    "build_context",
    "render_dockerfile",
    "render_for_genome",
    "check_forbidden",
    "shq",
    "pkgjoin",
    "imgref",
    "urlv",
    "urlq",
]
