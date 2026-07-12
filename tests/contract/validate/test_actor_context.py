"""context/actor-context/v1 fixture validation (w1-11)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _support import (
    CONTRACTS_JSON_SCHEMA_DIR,
    IDENTIFIERS_SCHEMA,
    build_validator,
    fixture_pairs,
    load_json,
    strip_metadata,
)

SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR / "context" / "actor-context" / "v1" / "actor-context.schema.json"
)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "actor-context"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")


def _validator():  # type: ignore[no-untyped-def]
    return build_validator(SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA])


def test_fixture_inventory_complete() -> None:
    assert len(VALID_FIXTURES) == 2
    assert len(INVALID_FIXTURES) == 4


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


def test_human_without_tenant_id_violation_names_tenant_id() -> None:
    """Spot check: the human=>tenant_id if/then conditional (Security
    MUST-FIX 2) must surface a tenant_id-referencing violation, not just
    any error, so the fixture actually exercises the conditional branch
    rather than failing for an unrelated reason.
    """
    validator = _validator()
    fixture_path = FIXTURE_DIR / "invalid" / "human-without-tenant-id.json"
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    messages = " ".join(e.message for e in errors)
    assert "tenant_id" in messages, f"expected a tenant_id-referencing error, got: {messages}"


def test_email_property_violation_is_additional_properties() -> None:
    """Spot check: email-property.json must be rejected as an undeclared
    (additionalProperties:false) key, proving ActorContext structurally
    excludes identity fields rather than merely omitting them by chance.
    """
    validator = _validator()
    fixture_path = FIXTURE_DIR / "invalid" / "email-property.json"
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    messages = " ".join(e.message for e in errors)
    assert "email" in messages or "additional" in messages.lower(), (
        f"expected an additionalProperties/email-referencing error, got: {messages}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
