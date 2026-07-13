"""domain/platform-observation/v1 fixture validation (w4-10 Contracts Steward)."""

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
    / "platform-observation"
    / "v1"
    / "platform-observation.schema.json"
)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "platform-observation"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")


def _validator():  # type: ignore[no-untyped-def]
    return build_validator(SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA])


def test_fixture_inventory_complete() -> None:
    assert len(VALID_FIXTURES) == 2
    assert len(INVALID_FIXTURES) == 2


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


def test_zero_citations_is_valid_signal_never_rejected() -> None:
    """chatgpt-observer-service README precedent: citation_refs empty array is
    schema-valid, always present (required)."""
    validator = _validator()
    fixture_path = FIXTURE_DIR / "valid" / "zero-citations.json"
    data = strip_metadata(load_json(fixture_path))
    assert data["citation_refs"] == []
    errors = list(validator.iter_errors(data))
    assert not errors, (
        f"expected zero-citations instance to be valid: {[e.message for e in errors]}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
