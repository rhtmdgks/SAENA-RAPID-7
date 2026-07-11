"""Contract fixture tests for the draft envelope schema (ADR-0013).

Validates:
  - the 3 valid envelope example instances (from ADR-0013 appendix) pass
    schema validation against the draft envelope schema.
  - the 3 schema-detectable invalid fixtures (a, b, c) FAIL schema
    validation for their documented reasons.
  - the 4th invalid fixture (cohort-below-threshold) is schema-VALID
    (by design — the k-anonymity relation cannot be expressed in JSON
    Schema 2020-12, per ADR-0013) but is caught by a dedicated inline
    runtime-gate check, which stands in for the W2A publish-side gate.

Invocation strategy: subprocess `uv run check-jsonschema --schemafile
<draft> <instance>`, per the harness design in tests/contract/README.md.
Fixture metadata keys (`_expected_violation`, `_note`) are stripped
before validation so that `unevaluatedProperties: false` does not mask
the real, documented violation with an unrelated "extra property"
error — see tests/contract/README.md "fixture metadata convention".
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "envelope"
SCHEMA_PATH = FIXTURES_DIR / "draft-envelope.schema.json"
VALID_DIR = FIXTURES_DIR / "valid"
INVALID_DIR = FIXTURES_DIR / "invalid"

# Fixture metadata keys that are part of the fixture-authoring convention
# (see tests/contract/README.md) and must never be treated as instance
# payload content when invoking a schema validator.
METADATA_KEYS = ("_expected_violation", "_note")

VALID_FIXTURES = sorted(VALID_DIR.glob("*.json"))
INVALID_FIXTURES = sorted(INVALID_DIR.glob("*.json"))

# (d) is schema-valid by design (ADR-0013 k-anonymity relation is not
# schema-expressible) — it is excluded from the "must fail schema
# validation" set and covered by its own dedicated runtime-gate test.
SCHEMA_INVALID_FIXTURE_NAMES = {
    "aggregate-with-tenant-id.json",
    "system-with-run-id.json",
    "engine-id-google.json",
}
RUNTIME_GATE_ONLY_FIXTURE_NAME = "cohort-below-threshold.json"


def _strip_metadata_to_tempfile(fixture_path: Path, tmp_path: Path) -> Path:
    """Write a copy of fixture_path with metadata keys removed, return its path."""
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    for key in METADATA_KEYS:
        data.pop(key, None)
    out_path = tmp_path / fixture_path.name
    out_path.write_text(json.dumps(data), encoding="utf-8")
    return out_path


def _run_check_jsonschema(instance_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "check-jsonschema",
            "--schemafile",
            str(SCHEMA_PATH),
            str(instance_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_schema_file_exists() -> None:
    assert SCHEMA_PATH.is_file(), f"draft envelope schema missing at {SCHEMA_PATH}"


def test_schema_is_valid_2020_12_metaschema() -> None:
    result = subprocess.run(
        ["uv", "run", "check-jsonschema", "--check-metaschema", str(SCHEMA_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"draft envelope schema failed metaschema check:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_fixture_inventory_complete() -> None:
    """Sanity check that this test module's expectations match the fixture dir contents."""
    valid_names = {p.name for p in VALID_FIXTURES}
    invalid_names = {p.name for p in INVALID_FIXTURES}

    assert len(valid_names) == 3, f"expected 3 valid fixtures, found {valid_names}"
    assert invalid_names == SCHEMA_INVALID_FIXTURE_NAMES | {RUNTIME_GATE_ONLY_FIXTURE_NAME}, (
        f"invalid fixture set mismatch: found {invalid_names}"
    )


@pytest.mark.parametrize("fixture_path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_envelope_fixtures_pass_schema(fixture_path: Path) -> None:
    result = _run_check_jsonschema(fixture_path)
    assert result.returncode == 0, (
        f"expected {fixture_path.name} to be schema-valid but check-jsonschema failed:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


@pytest.mark.parametrize(
    "fixture_path",
    [p for p in INVALID_FIXTURES if p.name in SCHEMA_INVALID_FIXTURE_NAMES],
    ids=lambda p: p.name,
)
def test_invalid_envelope_fixtures_fail_schema(fixture_path: Path, tmp_path: Path) -> None:
    """(a), (b), (c) — must fail schema validation for their documented reason.

    Metadata keys are stripped first so the failure reported is the real,
    documented structural violation rather than an incidental
    unevaluatedProperties hit on the fixture's own annotation fields.
    """
    stripped = _strip_metadata_to_tempfile(fixture_path, tmp_path)
    result = _run_check_jsonschema(stripped)
    assert result.returncode != 0, (
        f"expected {fixture_path.name} to FAIL schema validation but it passed:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_cohort_below_threshold_fixture_passes_schema_validation() -> None:
    """(d) is schema-VALID by design (ADR-0013): cohort_size >= privacy_threshold
    is a relational invariant JSON Schema 2020-12 cannot express. This test
    documents/locks that fact — if it ever starts failing schema validation,
    someone added cross-field validation to the draft schema and the
    accompanying runtime-gate rationale in ADR-0013 / this fixture's
    `_note` needs to be revisited.
    """
    fixture_path = INVALID_DIR / RUNTIME_GATE_ONLY_FIXTURE_NAME
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert data.get("_note"), "permanent runtime-gate fixture must retain its _note field"

    with tempfile.TemporaryDirectory() as tmp_dir:
        stripped = _strip_metadata_to_tempfile(fixture_path, Path(tmp_dir))
        result = _run_check_jsonschema(stripped)

    assert result.returncode == 0, (
        "expected cohort-below-threshold.json to PASS schema validation "
        "(k-anonymity relation is not schema-expressible per ADR-0013) "
        f"but it failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def _runtime_gate_check(cohort_size: int, privacy_threshold: int) -> None:
    """Reference runtime-gate logic (ADR-0013 W2A obligation).

    Raises ValueError if the k-anonymity invariant is violated. This is a
    minimal stand-in for the publish-side gate that W2A will implement in
    the actual event producer path; it exists here to prove the invariant
    the schema cannot enforce is at least enforced somewhere in this repo's
    test suite, and to give W2A a documented reference implementation.
    """
    if cohort_size < privacy_threshold:
        raise ValueError(
            f"k-anonymity violation: cohort_size ({cohort_size}) < "
            f"privacy_threshold ({privacy_threshold})"
        )


def test_runtime_gate_catches_cohort_below_threshold() -> None:
    """Dedicated test asserting the cohort_size >= privacy_threshold check
    catches what the schema cannot (ADR-0013 runtime-gate obligation).
    """
    fixture_path = INVALID_DIR / RUNTIME_GATE_ONLY_FIXTURE_NAME
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="k-anonymity violation"):
        _runtime_gate_check(data["cohort_size"], data["privacy_threshold"])


def test_runtime_gate_passes_valid_aggregate_fixture() -> None:
    """Control case: the valid aggregate fixture (cohort_size=12 >=
    privacy_threshold=5) must NOT trip the runtime gate.
    """
    fixture_path = VALID_DIR / "aggregate-strategy-card-eligible-v1.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    _runtime_gate_check(data["cohort_size"], data["privacy_threshold"])  # must not raise


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
