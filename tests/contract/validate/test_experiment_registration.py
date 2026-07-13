"""domain/experiment-registration/v1 fixture validation (w4-10 Contracts Steward).

QueryExperiment pre-registration record — registration ONLY, NO outcome/DiD/
causal/lift fields (docs/architecture/wave4-plan.md "Forbidden in W4").
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

SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR
    / "domain"
    / "experiment-registration"
    / "v1"
    / "experiment-registration.schema.json"
)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "experiment-registration"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")

_NO_OUTCOME_FIELDS = frozenset(
    {"lift_pct", "did_estimate", "p_value", "outcome", "kpi_weight", "causal_estimate"}
)


def _validator():  # type: ignore[no-untyped-def]
    return build_validator(SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA])


def test_fixture_inventory_complete() -> None:
    assert len(VALID_FIXTURES) == 2
    assert len(INVALID_FIXTURES) == 3


@pytest.mark.parametrize("fixture_path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_fixture_passes(fixture_path: Path) -> None:
    validator = _validator()
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    assert not errors, f"expected {fixture_path.name} to be valid: {[e.message for e in errors]}"


@pytest.mark.parametrize("fixture_path", INVALID_FIXTURES, ids=lambda p: p.name)
def test_invalid_fixture_fails(fixture_path: Path) -> None:
    validator = _validator()
    raw = load_json(fixture_path)
    data = strip_metadata(raw)
    errors = list(validator.iter_errors(data))
    assert errors, f"expected {fixture_path.name} to FAIL validation but it passed"
    assert raw.get("_expected_violation")


@pytest.mark.parametrize("fixture_path", VALID_FIXTURES, ids=lambda p: p.name)
def test_no_outcome_fields_present_registration_only(fixture_path: Path) -> None:
    """wave4-plan.md 'Forbidden in W4' -- registration is outcome-free by
    construction (this catalog carries no outcome/DiD/causal/lift field at
    all, closed-class additionalProperties:false makes this schema-enforced,
    unlike the open-class event payload gap)."""
    data = strip_metadata(load_json(fixture_path))
    present_outcome_fields = _NO_OUTCOME_FIELDS & data.keys()
    assert not present_outcome_fields, (
        f"{fixture_path.name}: unexpected outcome field(s) {present_outcome_fields} in a "
        "registration-only fixture"
    )


def test_genesis_previous_hash_null_accepted() -> None:
    validator = _validator()
    data = strip_metadata(load_json(FIXTURE_DIR / "valid" / "basic.json"))
    assert data["previous_hash"] is None
    errors = list(validator.iter_errors(data))
    assert not errors


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
