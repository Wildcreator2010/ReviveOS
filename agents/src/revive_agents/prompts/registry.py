"""Versioned prompt registry (T-AG-02).

Prompts live at 'prompts/<name>/vN.md' and every file must end with a line
'OUTPUT_CONTRACT: <schema name>'.  Nodes must render prompts through this
module: inline multi-line prompt strings are forbidden.  Rendering validates
required variables and substitutes only named placeholders, so literal braces
inside a prompt stay intact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent

_PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*)\}")
_CONTRACT = re.compile(r"^\s*OUTPUT_CONTRACT:\s*(\S+)\s*$", re.MULTILINE)
_VERSION = re.compile(r"^v(\d+)$")


class PromptVarsError(ValueError):
    """A required prompt variable was not supplied by the caller."""


class PromptContractError(ValueError):
    """A prompt file is missing its OUTPUT_CONTRACT declaration."""


def _prompt_path(name: str, version: str) -> Path:
    return ROOT / name / f"{version}.md"


def resolve_version(name: str, version: str | None = None) -> str:
    if version:
        if not _prompt_path(name, version).is_file():
            raise FileNotFoundError(f"prompt {name!r} has no {version}.md")
        return version
    directory = ROOT / name
    if not directory.is_dir():
        raise FileNotFoundError(f"prompt {name!r} not found under {ROOT}")
    versions: list[tuple[int, str]] = []
    for path in directory.glob("v*.md"):
        match = _VERSION.match(path.stem)
        if match:
            versions.append((int(match.group(1)), path.stem))
    if not versions:
        raise FileNotFoundError(f"prompt {name!r} has no versioned markdown files")
    return max(versions)[1]


def load(name: str, version: str | None = None) -> str:
    resolved = resolve_version(name, version)
    return _prompt_path(name, resolved).read_text(encoding="utf-8")


def output_contract(name: str, version: str | None = None) -> str:
    text = load(name, version)
    match = _CONTRACT.search(text)
    if not match:
        raise PromptContractError(f"prompt {name!r} must declare 'OUTPUT_CONTRACT: <schema>'")
    return match.group(1)


def required_vars(name: str, version: str | None = None) -> list[str]:
    return sorted(set(_PLACEHOLDER.findall(load(name, version))))


def render(name: str, version: str | None = None, **variables: Any) -> list[dict[str, str]]:
    text = load(name, version)
    required = set(_PLACEHOLDER.findall(text))
    missing = sorted(required - set(variables))
    if missing:
        raise PromptVarsError("missing variables: " + ", ".join(missing))

    def _substitute(match: re.Match[str]) -> str:
        return str(variables[match.group(1)])

    content = _PLACEHOLDER.sub(_substitute, text)
    return [{"role": "system", "content": content}]


def message_hash(messages: Sequence[dict[str, Any]]) -> str:
    canonical = [dict(message) for message in messages]
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def list_prompts() -> list[str]:
    return sorted(directory.name for directory in ROOT.iterdir() if directory.is_dir())
