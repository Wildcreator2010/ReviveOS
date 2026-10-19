"""Extract the runtime base image from a Dockerfile (multi-stage aware)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from ..evidence import EvidenceItem, EvidenceReference, ExtractContext
from .common import normalize_python_version

FROM_RE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+[Aa][Ss]\s+(\S+))?\s*$")
_BUILDER_RE = re.compile(r"build", re.IGNORECASE)


def matches(rel_path: str) -> bool:
    name = PurePosixPath(rel_path).name
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def _split_image(image: str) -> tuple[str, str]:
    if "@" in image:
        image = image.split("@", 1)[0]
    last = image.rsplit("/", 1)[-1]
    if ":" in last:
        name, tag = image.rsplit(":", 1)
        return name, tag
    return image, ""


def _detect_os(name: str, tag: str) -> str | None:
    haystack = f"{name}:{tag}".lower()
    for distro in ("ubuntu", "debian", "alpine", "centos", "rockylinux", "fedora", "windows"):
        match = re.search(rf"{distro}(\d+(?:\.\d+)?)?", haystack)
        if match:
            return distro + (match.group(1) or "")
    if "slim" in tag or "buster" in tag or "bookworm" in tag:
        return "debian"
    return None


def _classify(name: str, tag: str) -> dict:
    facts: dict = {}
    lowered = name.lower()
    if lowered.endswith("python") or lowered == "python":
        facts["python_version"] = normalize_python_version(tag)
    cuda_match = re.search(r"cuda[-_:=]?(\d+(?:\.\d+)?)", f"{lowered}:{tag}")
    if cuda_match:
        facts["cuda_version"] = cuda_match.group(1)
    os_value = _detect_os(name, tag)
    if os_value:
        facts["os_distro"] = os_value
    python_match = re.search(r"python[-_:]?(\d+\.\d+)", f"{lowered}:{tag}")
    if python_match and "python_version" not in facts:
        facts["python_version"] = normalize_python_version(python_match.group(1))
    return facts


def extract(rel_path: str, text: str, ctx: ExtractContext) -> list[EvidenceItem]:
    stages: list[dict] = []
    for line in text.splitlines():
        match = FROM_RE.match(line)
        if not match:
            continue
        image, alias = match.group(1), match.group(2)
        if "$" in image:
            continue
        name, tag = _split_image(image)
        stages.append({"image": image, "name": name, "tag": tag, "alias": alias})
    if not stages:
        return []

    builder_aliases = {s["alias"] for s in stages if s["alias"] and _BUILDER_RE.search(s["alias"])}
    known_aliases = {s["alias"] for s in stages if s["alias"]}
    chosen = None
    for stage in stages:
        alias = stage["alias"]
        if alias and alias in builder_aliases:
            continue
        if stage["name"] in known_aliases and stage["name"] in builder_aliases:
            continue
        chosen = stage
        break
    if chosen is None:
        chosen = stages[-1]

    facts = {
        "base_image": chosen["image"],
        "base_image_tag": chosen["tag"],
        "dockerfile_stages": [
            {
                "image": s["image"],
                "alias": s["alias"],
                "is_builder": bool(s["alias"] and s["alias"] in builder_aliases),
            }
            for s in stages
        ],
    }
    facts.update(_classify(chosen["name"], chosen["tag"]))
    return [
        EvidenceItem(
            source_kind="manifest_file",
            reference=EvidenceReference(file=rel_path, commit_sha=ctx.commit_sha),
            facts=facts,
        )
    ]
