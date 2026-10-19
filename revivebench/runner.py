import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
import uuid
from pathlib import Path

from .schema import validate_entry


def env():
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        sha = "unknown"
    return {
        "docker_version": "unknown",
        "host_spec": platform.platform(),
        "commit_sha_of_reviveos": sha,
        "llm_provider_model_redacted": os.getenv("LLM_PROVIDER_MODEL", "redacted"),
    }


def run(dataset, arms, limit=None, out="results"):
    rows = [json.loads(x) for x in Path(dataset).read_text().splitlines() if x.strip()]
    rows = rows[:limit] if limit else rows
    rid = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    Path(out).mkdir(parents=True, exist_ok=True)
    fp = Path(out) / (rid + ".jsonl")
    with fp.open("w", encoding="utf8") as f:
        for x in rows:
            for arm in arms:
                try:
                    validate_entry(x)
                    outcome = "pending"
                    failure = [{"stage": "execution", "error_signature": "not_run"}]
                except Exception as e:
                    outcome = "failed"
                    failure = [{"stage": "validation", "error_signature": type(e).__name__ + ":" + str(e)}]
                rec = {
                    "run_id": rid,
                    "ts": datetime.datetime.now(datetime.UTC).isoformat(),
                    "repo": x.get("repo", ""),
                    "arm": arm,
                    "outcome": outcome,
                    "metrics": {},
                    "environment_fingerprint": env(),
                    "artifacts_ref": None,
                    "failures": failure,
                }
                f.write(json.dumps(rec, sort_keys=True) + "\n")
    Path(out, f"{rid}.manifest.json").write_text(
        json.dumps(
            {
                "run_id": rid,
                "dataset": str(dataset),
                "dataset_sha256": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
                "arms": arms,
                "JOB_BUDGET_USD": os.getenv("JOB_BUDGET_USD", "unset"),
                "environment": env(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return fp


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("dataset")
    p.add_argument("--arms", default="ABCD")
    p.add_argument("--limit", type=int)
    p.add_argument("--out", default="results")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if a.dry_run:
        print(
            json.dumps({"dataset": a.dataset, "arms": list(a.arms), "limit": a.limit, "dry_run": True}, sort_keys=True)
        )
        return 0
    print(run(a.dataset, list(a.arms), a.limit, a.out))
    return 0
