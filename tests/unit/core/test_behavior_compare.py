from revive_core.behavior.compare import compare


def _fingerprint(*, output_files=None, structural=None):
    return {
        "format": "revive-behavior/v1",
        "plan_ref": "plan.json",
        "captured_at": "2026-01-01T00:00:00Z",
        "cases": [
            {
                "id": "case-1",
                "exit_code": 0,
                "stdout_hash": "same",
                "output_files": output_files or [],
                "structural": structural,
            }
        ],
    }


def test_exact_comparison_penalizes_unexpected_output_file() -> None:
    baseline = _fingerprint(output_files=[{"glob": "expected.txt", "sha256": "a"}])
    after = _fingerprint(
        output_files=[
            {"glob": "expected.txt", "sha256": "a"},
            {"glob": "unexpected.txt", "sha256": "b"},
        ]
    )

    result = compare(baseline, after)

    assert result.ok is False
    assert result.compatibility is not None and result.compatibility < 1.0
    assert "case-1.output_files[unexpected.txt]:unexpected" in result.drifted_fields


def test_structural_comparison_penalizes_unexpected_leaf() -> None:
    baseline = _fingerprint(structural={"result": {"value": 1}})
    after = _fingerprint(structural={"result": {"value": 1, "extra": True}})

    result = compare(baseline, after, {"default": {"mode": "structural"}})

    assert result.ok is False
    assert result.compatibility == 0.5
    assert "case-1.structural.result.extra:unexpected" in result.drifted_fields
