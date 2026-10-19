"""Environment genome domain model.

Field-for-field mirror of schemas/environment-genome.schema.json. The models
forbid unknown fields so an accidental new key fails fast instead of silently
diverging from the frozen contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal[
    "git_history",
    "manifest_file",
    "ci_config",
    "doc",
    "release_artifact",
    "inference",
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKind
    reference: str
    note: str | None = None


class Inference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    image: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]


class Dependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    source: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]


class EnvironmentGenome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python: Inference
    os: Inference
    dependencies: list[Dependency]
    cuda: Inference
    system_libs: list[Inference]
    overall_confidence: float = Field(ge=0, le=1)


__all__ = ["SourceKind", "Evidence", "Inference", "Dependency", "EnvironmentGenome"]
