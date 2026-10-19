"""Hard permission ceiling for the LLM repair agent (global red line #7).

These constants are the maximum any task may grant.  They are enforced inside
'revive_agents.nodes.repairer' and must never be relaxed: any proposal beyond
them is returned as a Refused and never reaches the sandbox pipeline.
"""

from __future__ import annotations

MAX_ITERATIONS = 5
MAX_FILES = 10
MAX_LINES = 300

LIMITS = {
    "max_iterations": MAX_ITERATIONS,
    "max_files": MAX_FILES,
    "max_lines": MAX_LINES,
}

__all__ = ["MAX_ITERATIONS", "MAX_FILES", "MAX_LINES", "LIMITS"]
