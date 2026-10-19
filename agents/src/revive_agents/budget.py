"""Per-job LLM cost guard (T-AG-07).

Accumulates 'cost_usd_estimate' across a job and raises BudgetExceeded once the
limit (REVIVE_LLM__JOB_BUDGET_USD, default 2.0) is crossed.  The supervisor
turns that into 'job.failed' with reason 'budget'.  Costs come only from
provider-supplied usage; no vendor price is hard-coded here.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from .llm.base import BudgetExceeded, Usage

DEFAULT_JOB_BUDGET_USD = 2.0


def default_limit() -> float:
    raw = os.getenv("REVIVE_LLM__JOB_BUDGET_USD")
    if raw is None or raw == "":
        return DEFAULT_JOB_BUDGET_USD
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_JOB_BUDGET_USD


class JobBudget:
    """Mutable per-job accumulator; call 'charge' after each LLM call."""

    def __init__(self, limit: float | None = None, *, job_id: str = "") -> None:
        self.limit = default_limit() if limit is None else float(limit)
        self.job_id = job_id
        self.spent = 0.0
        self.calls = 0

    @property
    def remaining(self) -> float:
        return max(self.limit - self.spent, 0.0)

    @property
    def exceeded(self) -> bool:
        return self.spent > self.limit

    def charge(self, usage: Any) -> float:
        self.spent += float(Usage.coerce(usage).cost_usd_estimate)
        self.calls += 1
        if self.spent > self.limit:
            raise BudgetExceeded(f"LLM job budget {self.limit:.4f} exceeded (spent {self.spent:.4f})")
        return self.spent


class BudgetedProvider:
    """Provider decorator that enforces a JobBudget at the provider layer."""

    def __init__(self, provider: Any, budget: JobBudget) -> None:
        self.provider = provider
        self.budget = budget

    async def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        response_format: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 30.0,
    ) -> Any:
        if self.budget.spent >= self.budget.limit:
            raise BudgetExceeded(f"LLM job budget {self.budget.limit:.4f} is already exhausted")
        completion = await self.provider.complete(
            messages,
            response_format=response_format,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        self.budget.charge(getattr(completion, "usage", None))
        return completion
