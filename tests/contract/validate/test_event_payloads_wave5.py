"""event/*/v1 payload fixture validation for the 3 Wave 5 measurement event
payload contracts (w5-02 Contracts Steward).

Covers: deployment-confirmed, experiment-outcome-observed,
strategy-card-eligible -- sibling module to test_event_payloads.py (original
CONFIRMED-v1 "event/ 6종") and test_event_payloads_wave4.py (the 7 Wave 4
intelligence events). This module is the w5-02-owned extension for the
measurement contracts landed by this unit.

Also covers the B-gate gap fixture for experiment-outcome-observed
(experiment-outcome-observed/invalid/single-layer-pass-gap.json): schema-valid
(open-class payload, no additionalProperties:false, and JSON Schema cannot
express ">=2 independent signal layers required for a PASS") but
policy-forbidden by the B-gate rule (ALG §3.7-5:198) -- a policy-gate/review
obligation (w5-06), not schema-enforceable, same class of gap as
experiment-registered's outcome-field-gap and patch-unit-completed's
tenant-id-in-payload-gap. It is NOT faked in-schema.
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
    "deployment-confirmed": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "deployment-confirmed"
        / "v1"
        / "deployment-confirmed.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
    "experiment-outcome-observed": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "experiment-outcome-observed"
        / "v1"
        / "experiment-outcome-observed.schema.json",
        [IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA],
    ),
    "strategy-card-eligible": (
        CONTRACTS_JSON_SCHEMA_DIR
        / "event"
        / "strategy-card-eligible"
        / "v1"
        / "strategy-card-eligible.schema.json",
        [IDENTIFIERS_SCHEMA],
    ),
}

GAP_FIXTURE_NAMES = {"single-layer-pass-gap.json"}


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
    """The B-gate >=2-independent-layer PASS rule (ALG §3.7-5:198) BANS a
    single-layer b_verdict=pass, but an open-class payload schema (no
    additionalProperties:false, and no way to express ">=2 entries with
    distinct evidence_basis_id" as a PASS precondition) cannot itself reject
    it -- policy-gate/review obligation (w5-06), not schema-enforceable. Must
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


def test_gap_fixture_exists_for_bgate_single_layer_ban() -> None:
    all_gaps = [p for name in _CONTRACTS for p in _gap_fixtures(name)]
    assert len(all_gaps) == 1, (
        f"expected exactly 1 B-gate single-layer gap fixture, found {all_gaps}"
    )
    assert all_gaps[0].name == "single-layer-pass-gap.json"


def test_outcome_event_rejects_google_engine_id() -> None:
    """experiment-outcome-observed is engine-id-required (experiment 계열,
    ADR-0013) and closes engine_id to ['chatgpt-search'] -- a Google engine_id
    must be rejected (CLAUDE.md Engine scope: Google/Gemini disabled)."""
    invalid_names = {p.name for p in _invalid_fixtures("experiment-outcome-observed")}
    assert any("engine-id-google" in n for n in invalid_names), (
        f"expected an engine-id-google invalid fixture, found {invalid_names}"
    )


def test_deployment_confirmed_is_not_engine_id_required_family() -> None:
    """deployment-confirmed carries NO engine_id and must NOT reference the
    engine_required_payload fragment -- it is a customer/CI-CD signal, not an
    engine observation (wave5-plan.md deliverable 2)."""
    schema_path, _ = _CONTRACTS["deployment-confirmed"]
    text = schema_path.read_text(encoding="utf-8")
    assert "engine_required_payload" not in text, (
        "deployment-confirmed must NOT include the engine_required_payload fragment"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
