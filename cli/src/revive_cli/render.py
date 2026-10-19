"""Human-readable CLI rendering helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from rich.console import Console
from rich.table import Table


def render_genome(genome: Mapping[str, Any], console: Console) -> None:
    table = Table(title="environment genome")
    table.add_column("field")
    table.add_column("value")
    for name in ("python", "os", "cuda", "overall_confidence"):
        value = genome.get(name)
        if isinstance(value, Mapping):
            value = value.get("version") or value.get("image") or "unknown"
        table.add_row(name, str(value))
    console.print(table)


def render_json(value: Any, console: Console) -> None:
    console.print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def render_pipeline(result: Any, console: Console) -> None:
    console.print(f"status={result.status} score={result.score.total:.2f}")
    if result.capsule_path:
        console.print(f"capsule={result.capsule_path}")
    for event in result.events:
        event_type = event.get("type", "unknown")
        payload = event.get("payload", {})
        console.print(f"{event_type} {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


__all__ = ["render_genome", "render_json", "render_pipeline"]
