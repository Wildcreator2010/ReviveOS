"""Graph state for the supervisor main graph (T-AG-06).

Fields mirror the contract in docs/tasks/03; 'job_id', 'status' and
'failure_reason' are carried alongside so events and terminal states are
self-describing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphState:
    job_id: str = ""
    project: Any = None
    genome: Any = None
    sandbox_handle: Any = None
    build_attempts: int = 0
    error_facts: list[Any] = field(default_factory=list)
    patches: list[Any] = field(default_factory=list)
    behavior_plan: Any = None
    fingerprints: Any = None
    score: Any = None
    capsule_ref: Any = None
    iteration_counts: dict[str, int] = field(default_factory=dict)
    status: str = "pending"
    failure_reason: str = ""
