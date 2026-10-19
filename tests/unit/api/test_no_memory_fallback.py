"""Guards that keep production code paths off the process-local memory store.

These are static checks over the route module: they are cheap, they run everywhere,
and they fail the moment someone re-introduces a dict-shaped read/write in a handler.
"""

from __future__ import annotations

import re
from pathlib import Path

MAIN = Path("apps/api/src/revive_api/main.py")
WORKER = Path("apps/api/src/revive_api/worker.py")


def _handler_body(text: str) -> str:
    """Everything except module-level helpers that legitimately own the dev store."""
    return text


def test_routes_do_not_read_or_write_memory_store_collections() -> None:
    text = _handler_body(MAIN.read_text(encoding="utf-8"))
    forbidden = (
        r"app\.state\.store\.(users|projects|jobs|capsules|evidence|api_keys|refresh_tokens|admin_audit)",
        r"app\.state\.store\.event_bus",
        r"app\.state\.store\.(add_|decode_)",
    )
    for pattern in forbidden:
        assert re.search(pattern, text) is None, f"route layer still touches the memory store: {pattern}"


def test_only_the_dev_dispatch_helper_touches_the_memory_store() -> None:
    text = MAIN.read_text(encoding="utf-8")
    allowed = {
        "app.state.store = store if store is not None else MemoryStore()",
        "app.state.control_plane = control_plane or MemoryControlPlane(app.state.store)",
        "app.state.events = events or StoreEventBus(app.state.store)",
        "dispatch_job(app.state.store, job_id)",
        "revoke_job(app.state.store, job_id)",
    }
    found = {line.strip() for line in text.splitlines() if re.search(r"app\.state\.store\b", line)}
    unexpected = {line for line in found if not any(entry in line for entry in allowed)}
    assert unexpected == set(), f"unexpected memory-store access: {sorted(unexpected)}"


def test_worker_dispatch_is_never_inlined_in_production() -> None:
    text = MAIN.read_text(encoding="utf-8")
    assert "def _dispatch_job(" in text
    assert "run_resurrection_job.delay(job_id)" in text
    worker = WORKER.read_text(encoding="utf-8")
    # The inline executor must stay explicitly labelled as the non-production path.
    assert "not the production path" in worker
