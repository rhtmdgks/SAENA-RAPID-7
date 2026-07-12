"""event/*/v1 payload fixture validation (w1-11).

Covers all 6 event payload contracts under
packages/contracts/json-schema/event/ (approved plan §2 "event/ 6종"):
patch-unit-completed, plan-contract-approved, plan-contract-proposed,
quality-gate-result, repo-intaken, site-inventory-completed. Fixtures
live under tests/contract/fixtures/event-payloads/<name>/{valid,invalid}
(README layout note: fixtures mirror registry.json entries, and these
6 event payload contracts are registry entries distinct from the
envelope itself).

Also covers the ADR-0024(e) tenant-id-in-payload gap fixture
(patch-unit-completed/invalid/tenant-id-in-payload-gap.json):
schema-valid (open-class payload, no additionalProperties:false) but
policy-forbidden re-projection of tenant_id into an event payload.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _support import (
    CONTRACTS_JSON_SCHEMA_DIR,
    ERROR_DETAIL_SCHEMA,
    IDENTIFIERS_SCHEMA,
    build_validator,
    fixture_pairs,
    load_json,
    strip_metadata,
)

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "event-payloads"

# name -> (schema relpath under json-schema/event/, extra $ref resource paths)
_CONTRACTS: dict[str, tuple[Path, list[Path]]] = {
    "patch-unit-completed": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "patch-unit-completed"
        / "v1"
        / "patch-unit-completed.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
    "plan-contract-approved": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "plan-contract-approved"
        / "v1"
        / "plan-contract-approved.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
    "plan-contract-proposed": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "plan-contract-proposed"
        / "v1"
        / "plan-contract-proposed.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
    "quality-gate-result": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "quality-gate-result"
        / "v1"
        / "quality-gate-result.schema.json",
        [IDENTIFIERS_SCHEMA, ERROR_DETAIL_SCHEMA],
    ),
    "repo-intaken": (
        CONTRACTS_JSON_SCHEMA_DIR / "event" / "repo-intaken" / "v1" / "repo-intaken.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
    "site-inventory-completed": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "site-inventory-completed"
        / "v1"
        / "site-inventory-completed.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
}

GAP_FIXTURE_NAMES = {"tenant-id-in-payload-gap.json"}


def _validator(name: str):  # type: ignore[no-untyped-def]
    schema_path, extras = _CONTRACTS[name]
    return build_validator(schema_path, extra_resource_paths=extras)


def _valid_fixtures(name: str) -> list[Path]:
    return fixture_pairs(FIXTURES_ROOT / name / "valid")


def _invalid_fixtures(name: str) -> list[Path]:
    return fixture_pairs(FIXTURES_ROOT / name / "invalid")


def _schema_invalid_fixtures(name: str) -> list[Path]:
    return [p for p in _invalid_fixtures(name) if p.name not in GAP_FIXTURE_NAMES]


def _gap_fixtures(name: str) -> list[Path]:
    return [p for p in _invalid_fixtures(name) if p.name in GAP_FIXTURE_NAMES]


@pytest.mark.parametrize("name", sorted(_CONTRACTS), ids=sorted(_CONTRACTS))
def test_fixture_inventory_one_valid_one_invalid_minimum(name: str) -> None:
    valid = _valid_fixtures(name)
    schema_invalid = _schema_invalid_fixtures(name)
    assert len(valid) == 1, f"{name}: expected 1 valid fixture, found {[p.name for p in valid]}"
    assert len(schema_invalid) == 1, (
        f"{name}: expected 1 schema-invalid fixture, found {[p.name for p in schema_invalid]}"
    )


_ALL_VALID_PARAMS = [
    pytest.param(name, path, id=f"{name}/{path.name}")
    for name in sorted(_CONTRACTS)
    for path in _valid_fixtures(name)
]

_ALL_SCHEMA_INVALID_PARAMS = [
    pytest.param(name, path, id=f"{name}/{path.name}")
    for name in sorted(_CONTRACTS)
    for path in _schema_invalid_fixtures(name)
]

_ALL_GAP_PARAMS = [
    pytest.param(name, path, id=f"{name}/{path.name}")
    for name in sorted(_CONTRACTS)
    for path in _gap_fixtures(name)
]


@pytest.mark.parametrize(("name", "fixture_path"), _ALL_VALID_PARAMS)
def test_valid_fixture_passes(name: str, fixture_path: Path) -> None:
    validator = _validator(name)
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    assert not errors, (
        f"expected {name}/{fixture_path.name} to be valid: {[e.message for e in errors]}"
    )


@pytest.mark.parametrize(("name", "fixture_path"), _ALL_SCHEMA_INVALID_PARAMS)
def test_invalid_fixture_fails(name: str, fixture_path: Path) -> None:
    validator = _validator(name)
    raw = load_json(fixture_path)
    data = strip_metadata(raw)
    errors = list(validator.iter_errors(data))
    assert errors, f"expected {name}/{fixture_path.name} to FAIL validation but it passed"
    assert raw.get("_expected_violation")


@pytest.mark.parametrize(("name", "fixture_path"), _ALL_GAP_PARAMS)
def test_gap_fixture_is_schema_valid_with_note(name: str, fixture_path: Path) -> None:
    """ADR-0024(e)-1 BANS tenant_id/run_id in event payloads, but an
    open-class payload schema (no additionalProperties:false) cannot
    itself reject an undeclared extra key -- this is a policy-gate/review
    obligation, not schema-enforceable. Must remain schema-VALID and
    carry a `_note`.
    """
    validator = _validator(name)
    raw = load_json(fixture_path)
    assert raw.get("_note"), f"{name}/{fixture_path.name} gap fixture must carry a _note field"
    assert not raw.get("_expected_violation")
    data = strip_metadata(raw)
    errors = list(validator.iter_errors(data))
    assert not errors, (
        f"expected gap fixture {name}/{fixture_path.name} to PASS schema validation but got: "
        + "; ".join(e.message for e in errors)
    )


def test_gap_fixture_exists_for_tenant_id_in_payload_ban() -> None:
    """At least one of the 6 event payload contracts must carry the
    ADR-0024(e)-1 tenant-id-in-payload gap fixture -- prevents silently
    dropping this required deliverable.
    """
    all_gaps = [p for name in _CONTRACTS for p in _gap_fixtures(name)]
    assert len(all_gaps) == 1, (
        f"expected exactly 1 tenant-id-in-payload gap fixture, found {all_gaps}"
    )
    assert all_gaps[0].name == "tenant-id-in-payload-gap.json"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
