"""Dependency-free Prometheus metrics for the API and workers."""

from __future__ import annotations

from collections import Counter, defaultdict
from time import monotonic


class Metrics:
    def __init__(self) -> None:
        self.jobs: Counter[str] = Counter()
        self.sandbox: Counter[str] = Counter()
        self.llm: defaultdict[tuple[str, str], float] = defaultdict(float)
        self.durations: list[float] = []
        self.repairs: list[int] = [0, 0]

    def job(self, outcome: str, duration: float | None = None) -> None:
        self.jobs[outcome] += 1
        if duration is not None:
            self.durations.append(float(duration))

    def sandbox_run(self, stage: str) -> None:
        self.sandbox[stage] += 1

    def llm_cost(self, provider: str, model: str, usd: float) -> None:
        self.llm[(provider, model)] += float(usd)

    def repair(self, success: bool) -> None:
        self.repairs[1] += 1
        self.repairs[0] += int(success)

    def render(self) -> str:
        lines = []
        for outcome, n in sorted(self.jobs.items()):
            lines.append(f'revive_jobs_total{{outcome="{outcome}"}} {n}')
        for stage, n in sorted(self.sandbox.items()):
            lines.append(f'revive_sandbox_runs_total{{stage="{stage}"}} {n}')
        for (provider, model), v in sorted(self.llm.items()):
            lines.append(f'revive_llm_cost_usd_total{{provider="{provider}",model="{model}"}} {v}')
        for d in self.durations:
            lines.append(f"revive_job_duration_seconds_sum {d}")
        ratio = self.repairs[0] / self.repairs[1] if self.repairs[1] else 0
        lines.append(f"revive_repair_success_ratio {ratio}")
        return "\n".join(lines) + "\n"


metrics = Metrics()


def observe_job(outcome: str, started: float, *, job_id: str | None = None, project_id: str | None = None) -> float:
    duration = monotonic() - started
    metrics.job(outcome, duration)
    return duration
