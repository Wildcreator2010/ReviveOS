"""Event-stream rendering for the CLI (T-CLI-01).

All event types from job-event.schema.json are rendered; an unknown type is
printed verbatim as JSON rather than dropped.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

EVENT_TYPES: tuple[str, ...] = (
    "job.queued",
    "archaeology.started",
    "archaeology.evidence",
    "env.inferred",
    "sandbox.created",
    "build.attempt",
    "build.failed",
    "repair.attempt",
    "repair.applied",
    "test.attempt",
    "behavior.captured",
    "behavior.compared",
    "score.computed",
    "capsule.created",
    "job.succeeded",
    "job.failed",
)

_STYLE: dict[str, str] = {
    "job.queued": "dim",
    "archaeology.started": "cyan",
    "archaeology.evidence": "cyan",
    "env.inferred": "cyan",
    "sandbox.created": "blue",
    "build.attempt": "yellow",
    "build.failed": "red",
    "repair.attempt": "magenta",
    "repair.applied": "magenta",
    "test.attempt": "yellow",
    "behavior.captured": "green",
    "behavior.compared": "green",
    "score.computed": "bold green",
    "capsule.created": "bold green",
    "job.succeeded": "bold green",
    "job.failed": "bold red",
}


def event_type(event: Mapping[str, Any]) -> str:
    """Accept both the job-event envelope and the graph's {type, payload} form."""

    if "type" in event:
        return str(event["type"])
    payload = event.get("payload")
    if isinstance(payload, Mapping) and "type" in payload:
        return str(payload["type"])
    return "unknown"


def event_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def render_event(event: Mapping[str, Any], console: Console) -> None:
    kind = event_type(event)
    style = _STYLE.get(kind, "white")
    payload = event_payload(event)
    if kind not in EVENT_TYPES:
        # Unknown types degrade to a raw JSON line, never silently dropped.
        console.print(json.dumps(dict(event), ensure_ascii=False, sort_keys=True))
        return
    detail = " ".join(f"{key}={value}" for key, value in payload.items() if value is not None)
    console.print(f"[{style}]{kind}[/{style}] {detail}".rstrip())


def events_table(events: Iterable[Mapping[str, Any]]) -> Table:
    table = Table(title="event timeline")
    table.add_column("type")
    table.add_column("payload")
    for event in events:
        table.add_row(event_type(event), json.dumps(event_payload(event), ensure_ascii=False, sort_keys=True))
    return table


def score_panel(score: Mapping[str, Any]) -> Panel:
    table = Table.grid(padding=(0, 2))
    components = score.get("components", {}) or {}
    for name in ("runtime", "dependencies", "build", "tests", "behavior", "reproducibility"):
        value = float(components.get(name, score.get(name, 0.0)) or 0.0)
        bars = int(round(value / 5))
        table.add_row(name, f"{value:6.1f} {'#' * bars}")
    table.add_row("total", f"{float(score.get('total', 0.0)):6.1f}")
    return Panel(table, title="resurrection score")


__all__ = [
    "EVENT_TYPES",
    "event_type",
    "event_payload",
    "render_event",
    "events_table",
    "score_panel",
]
