"""T-INIT-02: schemas/ is the single source of truth for the cross-stack contracts.

Every schema is checked for Draft 2020-12 validity, every fixture pair is checked
against the schema it maps to, and the job-event payload branches are checked
against the envelopes the API's development worker actually emits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from revive_agents.graph import EVENT_TYPES as GRAPH_EVENT_TYPES
from revive_api.config import Config
from revive_api.main import create_app
from revive_api.store import MemoryStore
from revive_api.worker import run_job
from revive_cli.jobs import EVENT_TYPES as CLI_EVENT_TYPES
from revive_core import schemas

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

CORE_CONTRACTS = ("revive-manifest", "environment-genome", "job-event", "resurrection-score")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def schema_paths() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.schema.json"))


def fixture_cases() -> list[tuple[Path, Path, str]]:
    cases = []
    for fixture in sorted(FIXTURE_DIR.glob("*.json")):
        if not fixture.stem.endswith(("-valid", "-invalid")):
            continue
        kind = "valid" if fixture.stem.endswith("-valid") else "invalid"
        key = fixture.stem.removesuffix("-valid").removesuffix("-invalid")
        matches = [path for path in schema_paths() if key in path.stem]
        assert len(matches) == 1, f"{fixture.name} maps to {matches}"
        cases.append((fixture, matches[0], kind))
    return cases


@pytest.mark.parametrize("path", schema_paths(), ids=lambda path: path.stem)
def test_schema_is_valid_draft_2020_12(path: Path) -> None:
    Draft202012Validator.check_schema(load_json(path))


@pytest.mark.parametrize(
    ("fixture", "schema_path", "kind"),
    fixture_cases(),
    ids=[fixture.name for fixture, _, _ in fixture_cases()],
)
def test_fixture_matches_its_schema(fixture: Path, schema_path: Path, kind: str) -> None:
    errors = list(Draft202012Validator(load_json(schema_path)).iter_errors(load_json(fixture)))
    if kind == "valid":
        assert not errors, f"{fixture.name} must validate: {errors[0].message}"
    else:
        assert errors, f"{fixture.name} must be rejected by {schema_path.name}"


@pytest.mark.parametrize("contract", CORE_CONTRACTS)
def test_core_contract_has_valid_and_invalid_fixtures(contract: str) -> None:
    kinds = {
        kind for _, schema_path, kind in fixture_cases() if schema_path.name.removesuffix(".schema.json") == contract
    }
    assert kinds == {"valid", "invalid"}


def test_score_valid_fixture_total_equals_weighted_sum() -> None:
    schema = load_json(SCHEMA_DIR / "resurrection-score.schema.json")
    score = load_json(FIXTURE_DIR / "score-valid.json")
    weights = schema["x-weights"]
    assert set(weights) == {
        "runtime",
        "dependencies",
        "build",
        "tests",
        "behavior",
        "reproducibility",
    }
    expected = round(sum(score[name] * weights[name] for name in weights), 2)
    assert score["total"] == pytest.approx(expected)


def test_event_type_enum_matches_the_code_side_tuples() -> None:
    enum = load_json(SCHEMA_DIR / "job-event.schema.json")["properties"]["type"]["enum"]
    assert sorted(enum) == sorted(CLI_EVENT_TYPES)
    assert sorted(enum) == sorted(GRAPH_EVENT_TYPES)
    assert len(enum) == len(set(enum)) == 16


def envelope(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "evt_000000000001",
        "job_id": "job_1",
        "project_id": "project_1",
        "ts": "2026-01-01T00:00:00Z",
        "type": event_type,
        "payload": payload,
    }


VALID_PAYLOADS: dict[str, dict[str, Any]] = {
    "job.queued": {"status": "queued"},
    "archaeology.started": {"status": "running", "low_confidence_fields": ["python"]},
    "archaeology.evidence": {"count": 2, "source": "https://github.com/acme/app", "warnings": ["no lockfile"]},
    "env.inferred": {"confidence": 0.42},
    "sandbox.created": {"backend": "development"},
    "build.attempt": {"attempt": 1, "ok": True},
    "build.failed": {"attempt": 2, "reason": "R05", "error_signature": "missing_shared_library"},
    "repair.attempt": {"attempt": 2},
    "repair.applied": {"applied": True, "attempt": 2},
    "test.attempt": {"ok": True, "tests_absent": True},
    "behavior.captured": {"cases": 3},
    "behavior.compared": {"matched": False},
    "score.computed": {"total": 61.5, "status": "partial"},
    "capsule.created": {"capsule_id": "rev_capsule_1"},
    "job.succeeded": {"status": "succeeded", "capsule_id": "rev_capsule_1"},
    "job.failed": {"status": "failed", "reason": "project_missing"},
}

INVALID_PAYLOADS: list[tuple[str, dict[str, Any], str]] = [
    ("job.queued", {}, "status is required"),
    ("job.succeeded", {"status": "partial"}, "terminal status is fixed to succeeded"),
    ("job.succeeded", {"status": "succeeded", "exit_code": 0}, "unknown payload key"),
    ("capsule.created", {"path": "/tmp/out.revive"}, "needs capsule_id or capsule_ref"),
    ("build.attempt", {"attempt": 0}, "attempt starts at 1"),
    ("build.failed", {"attempt": 1}, "reason is required"),
    ("env.inferred", {"confidence": "high"}, "confidence must be numeric"),
    ("archaeology.evidence", {"count": 1}, "warnings is required"),
    ("score.computed", {}, "total is required"),
    ("behavior.compared", {"compatibility": 1.0}, "matched is required"),
]


@pytest.mark.parametrize(
    ("event_type", "payload"),
    sorted(VALID_PAYLOADS.items()),
    ids=sorted(VALID_PAYLOADS),
)
def test_job_event_accepts_contracted_payload_branch(event_type: str, payload: dict[str, Any]) -> None:
    schemas.validate(envelope(event_type, payload), "job-event")


@pytest.mark.parametrize(
    ("event_type", "payload", "_why"),
    INVALID_PAYLOADS,
    ids=[f"{event_type}-{index}" for index, (event_type, _, _) in enumerate(INVALID_PAYLOADS, start=1)],
)
def test_job_event_rejects_payload_outside_its_type_branch(event_type: str, payload: dict[str, Any], _why: str) -> None:
    with pytest.raises(schemas.SchemaError):
        schemas.validate(envelope(event_type, payload), "job-event")


def test_job_event_rejects_unknown_type_and_extra_envelope_keys() -> None:
    with pytest.raises(schemas.SchemaError):
        schemas.validate(envelope("job.cancelled", {"status": "cancelled"}), "job-event")
    event = envelope("job.queued", {"status": "queued"})
    event["created_at"] = event["ts"]
    with pytest.raises(schemas.SchemaError):
        schemas.validate(event, "job-event")


def test_development_worker_emits_contract_valid_events() -> None:
    store = MemoryStore()
    project = store.add_project("user_1", "https://github.com/acme/worker")
    job = store.add_job(project)
    store.event_bus.publish(job.id, "job.queued", {"status": "queued"})
    run_job(store, job.id)

    events = [event.as_dict() for event in store.events_for_job(job.id)]
    assert [event["type"] for event in events] == [
        "job.queued",
        "archaeology.started",
        "archaeology.evidence",
        "env.inferred",
        "sandbox.created",
        "build.attempt",
        "test.attempt",
        "score.computed",
        "capsule.created",
        "job.succeeded",
    ]
    for event in events:
        schemas.validate(event, "job-event")


def test_development_worker_failure_event_stays_in_contract() -> None:
    store = MemoryStore()
    project = store.add_project("user_1", "https://github.com/acme/worker")
    job = store.add_job(project)
    store.projects.pop(project.id)
    run_job(store, job.id)

    events = [event.as_dict() for event in store.events_for_job(job.id)]
    assert [event["type"] for event in events] == ["job.failed"]
    for event in events:
        schemas.validate(event, "job-event")


def test_control_plane_cancel_and_kill_events_stay_in_contract() -> None:
    """Cancellation is expressed through job.failed; the interim signal stays on REST."""

    store = MemoryStore()
    client = TestClient(
        create_app(Config(jwt_secret="contract-test-secret-at-least-32-characters"), probes={}, store=store)
    )
    email = "admin@contract.example"
    registered = client.post("/auth/register", json={"email": email, "password": "correct-horse-123"})
    assert registered.status_code == 201
    store.users[store.users_by_email[email]].role = "admin"
    auth = {"Authorization": f"Bearer {registered.json()['access_token']}"}

    project = store.add_project(store.users_by_email[email], "https://github.com/acme/kill")
    job = store.add_job(project)

    cancel = client.post(f"/jobs/{job.id}/cancel", headers=auth)
    assert cancel.status_code == 200
    assert cancel.json()["cancel_requested"] is True
    assert client.get(f"/jobs/{job.id}/events", headers=auth).json() == []

    killed = client.post(f"/admin/jobs/{job.id}/kill", headers=auth)
    assert killed.status_code == 200, killed.text
    assert killed.json()["status"] == "cancelled"

    events = client.get(f"/jobs/{job.id}/events", headers=auth).json()
    assert [event["type"] for event in events] == ["job.failed"]
    assert events[0]["payload"] == {"status": "cancelled", "reason": "admin_killed"}
    for event in events:
        schemas.validate(event, "job-event")
