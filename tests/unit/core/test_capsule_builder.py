"""Capsule builder must not package files linked from outside the source tree."""

from __future__ import annotations

import io
import json
import tarfile
from hashlib import sha256
from pathlib import Path

import pytest
from revive_core.capsule.builder import RunState, build_capsule, build_entries, verify_capsule_structure
from revive_core.capsule.layout import DIGESTS, MANIFEST, SOURCE_TAR


def test_source_tar_skips_symlinks_that_point_outside_the_repo(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
    outside = tmp_path / "host-secret.txt"
    outside.write_text("HOST SECRET", encoding="utf-8")
    try:
        (source / "leak.txt").symlink_to(outside)
    except OSError:
        pytest.skip("creating symlinks is not permitted on this host")

    state = RunState(
        job_id="rev_job_symlink",
        source_repo="https://github.com/acme/demo",
        source_commit="abc1234",
        genome={},
        dockerfile="FROM python:3.11-slim\n",
        score={"total": 1.0, "components": {"runtime": 1.0}, "status": "partial"},
        created_at="2026-01-01T00:00:00Z",
        source_tree=source,
    )
    entries = dict(build_entries(state))

    with tarfile.open(fileobj=io.BytesIO(entries[SOURCE_TAR]), mode="r:") as archive:
        members = archive.getnames()

    assert "app.py" in members
    assert "leak.txt" not in members


def test_manifest_sbom_digest_must_match_the_packaged_sbom(tmp_path: Path) -> None:
    state = RunState(
        job_id="rev_job_sbom",
        source_repo="https://github.com/acme/demo",
        source_commit="abc1234",
        genome={},
        dockerfile="FROM python:3.11-slim\n",
        score={"total": 1.0, "components": {"runtime": 1.0}, "status": "partial"},
        created_at="2026-01-01T00:00:00Z",
    )
    valid = build_capsule(state, tmp_path / "valid.revive")
    with tarfile.open(valid, mode="r:gz") as archive:
        members = {
            member.name: archive.extractfile(member).read() for member in archive.getmembers() if member.isfile()
        }

    manifest = json.loads(members[MANIFEST])
    manifest["sbom_digest"] = "0" * 64
    members[MANIFEST] = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    digests = json.loads(members[DIGESTS])
    digests["entries"][MANIFEST] = sha256(members[MANIFEST]).hexdigest()
    members[DIGESTS] = json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()

    tampered = tmp_path / "tampered.revive"
    with tarfile.open(tampered, mode="w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    report = verify_capsule_structure(tampered)

    assert report["digests_ok"] is False
    assert any("sbom_digest" in entry for entry in report["bad_entries"])
