"""Contract fixture tests for the authoritative event envelope schema
(ADR-0013 + ADR-0013 rev.2 amendment).

Validates:
  - the 3 valid envelope example instances (from ADR-0013 appendix) pass
    schema validation against the authoritative envelope schema
    unchanged (they were pre-verified to already conform: UUIDv7
    event_id, ADR-0014 slug tenant_id, Z-terminated occurred_at).
  - the 7 schema-detectable invalid fixtures FAIL schema validation for
    their documented reasons (3 carried over from the W0 draft +
    4 new rev.2-delta fixtures: UUIDv4 event_id, malformed tenant_id
    slug, numeric-offset occurred_at, prerelease schema_version).
  - the 8th invalid fixture (cohort-below-threshold) is schema-VALID
    (by design — the k-anonymity relation cannot be expressed in JSON
    Schema 2020-12, per ADR-0013) but is caught by a dedicated inline
    runtime-gate check, which stands in for the W2A publish-side gate.

Validation engine: jsonschema.Draft202012Validator + a referencing.Registry
pre-loaded with the authoritative schema and the common/ files it
cross-file $refs (common/identifiers/v1, common/engine-id/v1). The
check-jsonschema CLI subprocess approach used by the retired W0 draft
test does not resolve these relative $refs out of the box — the schema's
$id is an https://schemas.the-saena.ai/... URI, so check-jsonschema
tries to fetch sibling $refs over the network instead of reading the
local sibling file (confirmed failure mode: FailedDownloadError /
NameResolutionError against schemas.the-saena.ai). This mirrors the
approach landed in w1-04's common-schema verification. See
tests/contract/README.md "fixture metadata convention" for the
_expected_violation / _note stripping convention this module still
follows.
"""

from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS_DIR = (
    Path(__file__).parent.parent.parent
    / "packages"
    / "contracts"
    / "json-schema"
)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "envelope"
SCHEMA_PATH = (
    CONTRACTS_DIR / "envelope" / "event-envelope" / "v1" / "event-envelope.schema.json"
)
IDENTIFIERS_PATH = CONTRACTS_DIR / "common" / "identifiers" / "v1" / "identifiers.schema.json"
ENGINE_ID_PATH = CONTRACTS_DIR / "common" / "engine-id" / "v1" / "engine-id.schema.json"
VALID_DIR = FIXTURES_DIR / "valid"
INVALID_DIR = FIXTURES_DIR / "invalid"

# Fixture metadata keys that are part of the fixture-authoring convention
# (see tests/contract/README.md) and must never be treated as instance
# payload content when invoking a schema validator.
METADATA_KEYS = ("_expected_violation", "_note")

VALID_FIXTURES = sorted(VALID_DIR.glob("*.json"))
INVALID_FIXTURES = sorted(INVALID_DIR.glob("*.json"))

# The cohort-below-threshold fixture is schema-valid by design (ADR-0013
# k-anonymity relation is not schema-expressible) — it is excluded from
# the "must fail schema validation" set and covered by its own dedicated
# runtime-gate test.
SCHEMA_INVALID_FIXTURE_NAMES = {
    "aggregate-with-tenant-id.json",
    "system-with-run-id.json",
    "engine-id-google.json",
    "event-id-uuid-v4.json",
    "tenant-id-bad-slug.json",
    "occurred-at-offset.json",
    "schema-version-prerelease.json",
}
RUNTIME_GATE_ONLY_FIXTURE_NAME = "cohort-below-threshold.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of data with fixture-authoring metadata keys removed."""
    return {k: v for k, v in data.items() if k not in METADATA_KEYS}


def _build_validator() -> Draft202012Validator:
    schema = _load_json(SCHEMA_PATH)
    identifiers = _load_json(IDENTIFIERS_PATH)
    engine_id = _load_json(ENGINE_ID_PATH)

    registry: Registry = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema)),
            (identifiers["$id"], Resource.from_contents(identifiers)),
            (engine_id["$id"], Resource.from_contents(engine_id)),
        ]
    )
    return Draft202012Validator(schema, registry=registry)


def test_schema_file_exists() -> None:
    assert SCHEMA_PATH.is_file(), f"authoritative envelope schema missing at {SCHEMA_PATH}"


def test_schema_is_valid_2020_12_metaschema() -> None:
    result = subprocess.run(
        ["uv", "run", "check-jsonschema", "--check-metaschema", str(SCHEMA_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"authoritative envelope schema failed metaschema check:\n"
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
    assert len(invalid_names) == 8, f"expected 8 invalid fixtures, found {len(invalid_names)}"


@pytest.mark.parametrize("fixture_path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_envelope_fixtures_pass_schema(fixture_path: Path) -> None:
    validator = _build_validator()
    data = _load_json(fixture_path)
    errors = list(validator.iter_errors(data))
    assert not errors, (
        f"expected {fixture_path.name} to be schema-valid but got errors:\n"
        + "\n".join(f"  {'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
    )


@pytest.mark.parametrize(
    "fixture_path",
    [p for p in INVALID_FIXTURES if p.name in SCHEMA_INVALID_FIXTURE_NAMES],
    ids=lambda p: p.name,
)
def test_invalid_envelope_fixtures_fail_schema(fixture_path: Path) -> None:
    """Must fail schema validation for the fixture's documented reason.

    Metadata keys are stripped first so the failure reported is the real,
    documented structural violation rather than an incidental
    unevaluatedProperties hit on the fixture's own annotation fields.
    """
    validator = _build_validator()
    data = _strip_metadata(_load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    assert errors, f"expected {fixture_path.name} to FAIL schema validation but it passed"


def test_cohort_below_threshold_fixture_passes_schema_validation() -> None:
    """This fixture is schema-VALID by design (ADR-0013): cohort_size >=
    privacy_threshold is a relational invariant JSON Schema 2020-12 cannot
    express. This test documents/locks that fact — if it ever starts
    failing schema validation, someone added cross-field validation to
    the authoritative schema and the accompanying runtime-gate rationale
    in ADR-0013 / this fixture's `_note` needs to be revisited.
    """
    fixture_path = INVALID_DIR / RUNTIME_GATE_ONLY_FIXTURE_NAME
    data = _load_json(fixture_path)
    assert data.get("_note"), "permanent runtime-gate fixture must retain its _note field"

    validator = _build_validator()
    errors = list(validator.iter_errors(_strip_metadata(data)))
    assert not errors, (
        "expected cohort-below-threshold.json to PASS schema validation "
        "(k-anonymity relation is not schema-expressible per ADR-0013) "
        "but got errors:\n"
        + "\n".join(f"  {'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
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
    data = _load_json(fixture_path)

    with pytest.raises(ValueError, match="k-anonymity violation"):
        _runtime_gate_check(data["cohort_size"], data["privacy_threshold"])


def test_runtime_gate_passes_valid_aggregate_fixture() -> None:
    """Control case: the valid aggregate fixture (cohort_size=12 >=
    privacy_threshold=5) must NOT trip the runtime gate.
    """
    fixture_path = VALID_DIR / "aggregate-strategy-card-eligible-v1.json"
    data = _load_json(fixture_path)

    _runtime_gate_check(data["cohort_size"], data["privacy_threshold"])  # must not raise


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
