import json
from pathlib import Path

DATA_FIELDS = {
    "repo",
    "commit_pinned",
    "license",
    "stars_at_pin",
    "last_activity",
    "death_reasons",
    "size_mb",
    "has_tests",
    "has_ci",
    "has_dockerfile",
    "python_requires_evidence",
    "notes",
}
RESULT_FIELDS = {
    "run_id",
    "ts",
    "repo",
    "arm",
    "outcome",
    "metrics",
    "environment_fingerprint",
    "artifacts_ref",
    "failures",
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_entry(x):
    missing = DATA_FIELDS - set(x)
    if missing:
        raise ValueError("missing fields: " + ", ".join(sorted(missing)))
    if not isinstance(x["death_reasons"], list) or any(
        r not in {f"R{i:02d}" for i in range(1, 9)} for r in x["death_reasons"]
    ):
        raise ValueError("invalid death_reasons")
    if not x["repo"] or not x["commit_pinned"]:
        raise ValueError("repo and commit_pinned required")
    return True


def validate_result(x):
    missing = RESULT_FIELDS - set(x)
    if missing:
        raise ValueError("missing fields: " + ", ".join(sorted(missing)))
    if x["arm"] not in "ABCD":
        raise ValueError("arm must be A-D")
    return True
