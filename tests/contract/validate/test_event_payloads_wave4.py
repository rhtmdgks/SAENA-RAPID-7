"""event/*/v1 payload fixture validation for the 7 Wave 4 NEW/newly-landed
event payload contracts (w4-10 Contracts Steward).

Covers: demand-graph-versioned, entity-graph-versioned,
claim-evidence-versioned, citation-normalized, observation-captured,
experiment-registered, experiment-anchored -- sibling module to
test_event_payloads.py (which stays scoped to the original CONFIRMED-v1
"event/ 6종" per its own docstring; this module is the w4-10-owned
extension for the Wave 4 contracts landed by this unit).

Also covers the ADR-0024(e)-1-style gap fixture for experiment-registered
(experiment-registered/invalid/outcome-field-gap.json): schema-valid
(open-class payload, no additionalProperties:false) but wave4-plan.md
"Forbidden in W4"-banned outcome/DiD/causal/lift field -- a policy-gate/
review obligation, not schema-enforceable, same class of gap as
patch-unit-completed's tenant-id-in-payload-gap fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _support import (
    CONTRACTS_JSON_SCHEMA_DIR,
    ENGINE_ID_SCHEMA,
    IDENTIFIERS_SCHEMA,
    build_validator,
    fixture_pairs,
    load_json,
    strip_metadata,
)

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "event-payloads"

# name -> (schema relpath under json-schema/event/, extra $ref resource paths)
_CONTRACTS: dict[str, tuple[Path, list[Path]]] = {
    "demand-graph-versioned": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "demand-graph-versioned"
        / "v1"
        / "demand-graph-versioned.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
    "entity-graph-versioned": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "entity-graph-versioned"
        / "v1"
        / "entity-graph-versioned.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
    "claim-evidence-versioned": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "claim-evidence-versioned"
        / "v1"
        / "claim-evidence-versioned.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
    "citation-normalized": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "citation-normalized"
        / "v1"
        / "citation-normalized.schema.json",
        [IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA],
    ),
    "observation-captured": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "observation-captured"
        / "v1"
        / "observation-captured.schema.json",
        [IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA],
    ),
    "experiment-registered": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "experiment-registered"
        / "v1"
        / "experiment-registered.schema.json",
        [IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA],
    ),
    "experiment-anchored": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "experiment-anchored"
        / "v1"
        / "experiment-anchored.schema.json",
        [IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA],
    ),
}

GAP_FIXTURE_NAMES = {"outcome-field-gap.json"}


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
def test_fixture_inventory_at_least_one_valid_one_invalid(name: str) -> None:
    valid = _valid_fixtures(name)
    schema_invalid = _schema_invalid_fixtures(name)
    assert len(valid) >= 1, f"{name}: expected at least 1 valid fixture"
    assert len(schema_invalid) >= 1, f"{name}: expected at least 1 schema-invalid fixture"


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
    """wave4-plan.md 'Forbidden in W4' BANS outcome/DiD/causal/lift fields in
    experiment.registered.v1, but an open-class payload schema (no
    additionalProperties:false) cannot itself reject an undeclared extra
    key -- policy-gate/review obligation, not schema-enforceable. Must
    remain schema-VALID and carry a `_note`.
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


def test_gap_fixture_exists_for_experiment_registered_outcome_ban() -> None:
    all_gaps = [p for name in _CONTRACTS for p in _gap_fixtures(name)]
    assert len(all_gaps) == 1, f"expected exactly 1 outcome-field gap fixture, found {all_gaps}"
    assert all_gaps[0].name == "outcome-field-gap.json"


def test_engine_required_contracts_reject_missing_engine_id() -> None:
    """observation-captured/citation-normalized/experiment-registered/
    experiment-anchored all allOf-include the engine_required_payload
    fragment -- at least one dedicated missing-engine-id or bad-engine-id
    fixture must exist and fail for each of these 4 contracts (ADR-0013
    'observation·citation·experiment 계열' rule)."""
    engine_required = {
        "citation-normalized",
        "observation-captured",
        "experiment-registered",
        "experiment-anchored",
    }
    for name in engine_required:
        invalid_names = {p.name for p in _invalid_fixtures(name)}
        assert any("engine-id" in n for n in invalid_names), (
            f"{name}: expected a missing/bad-engine-id invalid fixture, found {invalid_names}"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
