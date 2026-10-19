"""Behaviour plan node (T-AG-05).

Turns an entry point, README excerpt and existing tests into an executable
behaviour plan for the sandbox.  Existing tests are wrapped preferentially;
cases that need the network or credentials are dropped.  The returned payload
has exactly the two schema keys, and every case is validated by pydantic with
'extra=forbid' so a stray field is rejected rather than silently persisted.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..llm.base import BudgetExceeded, LLMError, LLMOutputError
from ..prompts import render

logger = logging.getLogger("revive_agents.behavior")

MAX_CASES = 25
DEFAULT_TIMEOUT_PER_CASE = 30.0

_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_SECRET_HINT_RE = re.compile(
    r"(?:sk|api[_-]?key|token|password|secret)[-_=:][A-Za-z0-9_\-]{6,}",
    re.IGNORECASE,
)

RESPONSE_FORMAT: dict[str, Any] = {
    "title": "behavior-plan",
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "argv": {"type": "array", "items": {"type": "string"}},
                    "stdin_file": {"type": ["string", "null"]},
                    "expect_files": {"type": "array", "items": {"type": "string"}},
                    "tolerance": {
                        "type": "object",
                        "properties": {
                            "mode": {"enum": ["exact", "numeric", "structural"]},
                            "eps": {"type": ["number", "null"]},
                        },
                    },
                },
                "required": ["id", "argv"],
            },
        }
    },
    "required": ["cases"],
}


class Tolerance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["exact", "numeric", "structural"] = "exact"
    eps: float | None = None


class BehaviorCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    argv: list[str]
    stdin_file: str | None = None
    expect_files: list[str] = Field(default_factory=list)
    tolerance: Tolerance = Field(default_factory=Tolerance)


class BehaviorBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_cases: int = MAX_CASES
    timeout_per_case: float = DEFAULT_TIMEOUT_PER_CASE


class BehaviorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cases: list[BehaviorCase] = Field(default_factory=list)
    budget: BehaviorBudget = Field(default_factory=BehaviorBudget)


def network_target(argv: Sequence[str]) -> str | None:
    """Return the offending argv token when a case needs the outside world."""

    for token in argv:
        if _URL_SCHEME_RE.match(token):
            host = token.split("://", 1)[1].split("/", 1)[0].split("@")[-1]
            host = host.split(":", 1)[0]
            if host not in _ALLOWED_HOSTS:
                return token
        if token.startswith("git@") and ":" in token:
            return token
        if _SECRET_HINT_RE.search(token):
            return token
    return None


def _baseline_cases(tests_dir: str | None) -> list[BehaviorCase]:
    cases = [
        BehaviorCase(
            id="cli-help",
            argv=["--help"],
            expect_files=[],
            tolerance=Tolerance(mode="exact"),
        )
    ]
    if tests_dir:
        cases.append(
            BehaviorCase(
                id="existing-tests",
                argv=["-m", "pytest", "-k", ""],
                expect_files=[],
                tolerance=Tolerance(mode="structural"),
            )
        )
    return cases


async def behavior_plan(
    source_tree_summary: Any,
    readme_excerpt: str,
    examples_dir: str | None = None,
    tests_dir: str | None = None,
    provider: Any = None,
    *,
    job_id: str = "",
) -> dict[str, Any]:
    cases = _baseline_cases(tests_dir)
    if provider is not None:
        messages = render(
            "behavior",
            source_tree=str(source_tree_summary),
            readme=str(readme_excerpt),
            tests_dir=str(tests_dir),
            examples_dir=str(examples_dir),
        )
        payload: dict[str, Any] | None = None
        try:
            completion = await provider.complete(messages, response_format=RESPONSE_FORMAT)
            payload = completion.json
        except BudgetExceeded:
            raise
        except (LLMOutputError, LLMError) as exc:
            logger.info("behavior_plan_llm_failed", extra={"reason": str(exc)})
        if isinstance(payload, dict):
            for raw in payload.get("cases") or []:
                try:
                    case = BehaviorCase.model_validate(raw)
                except ValidationError as exc:
                    logger.info(
                        "behavior_plan_case_rejected",
                        extra={"reason": exc.errors()[:1]},
                    )
                    continue
                offender = network_target(case.argv)
                if offender:
                    logger.info(
                        "behavior_plan_case_dropped_network",
                        extra={"case_id": case.id, "token": offender},
                    )
                    continue
                if any(existing.id == case.id for existing in cases):
                    continue
                if len(cases) >= MAX_CASES:
                    break
                cases.append(case)

    plan = BehaviorPlan(cases=cases[:MAX_CASES], budget=BehaviorBudget())
    return {
        "cases": [case.model_dump() for case in plan.cases],
        "budget": plan.budget.model_dump(),
    }
