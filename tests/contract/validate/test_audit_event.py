"""domain/audit-event/v1 fixture validation (w1-11)."""

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
    CONTRACTS_JSON_SCHEMA_DIR / "domain" / "audit-event" / "v1" / "audit-event.schema.json"
)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "audit-event"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")

GAP_FIXTURE_NAMES = {"payload-credential-like-value.json"}
SCHEMA_INVALID_FIXTURES = [p for p in INVALID_FIXTURES if p.name not in GAP_FIXTURE_NAMES]
GAP_FIXTURES = [p for p in INVALID_FIXTURES if p.name in GAP_FIXTURE_NAMES]


def _validator():  # type: ignore[no-untyped-def]
    return build_validator(SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA])


def test_fixture_inventory_complete() -> None:
    assert len(VALID_FIXTURES) == 3
    assert len(INVALID_FIXTURES) == 5, f"found {[p.name for p in INVALID_FIXTURES]}"
    assert len(SCHEMA_INVALID_FIXTURES) == 4
    assert len(GAP_FIXTURES) == 1


@pytest.mark.parametrize("fixture_path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_fixture_passes(fixture_path: Path) -> None:
    validator = _validator()
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    assert not errors, f"expected {fixture_path.name} to be valid: {[e.message for e in errors]}"


@pytest.mark.parametrize("fixture_path", SCHEMA_INVALID_FIXTURES, ids=lambda p: p.name)
def test_invalid_fixture_fails(fixture_path: Path) -> None:
    validator = _validator()
    raw = load_json(fixture_path)
    data = strip_metadata(raw)
    errors = list(validator.iter_errors(data))
    assert errors, f"expected {fixture_path.name} to FAIL validation but it passed"
    assert raw.get("_expected_violation")


@pytest.mark.parametrize("fixture_path", GAP_FIXTURES, ids=lambda p: p.name)
def test_gap_fixture_is_schema_valid_with_note(fixture_path: Path) -> None:
    """payload-credential-like-value.json is a PERMANENT gap (ADR-0015:64
    payload PII/secret exclusion is a runtime/review obligation, not
    schema-enforceable content inspection over a free-form payload
    object). Must remain schema-VALID and carry a `_note`.
    """
    validator = _validator()
    raw = load_json(fixture_path)
    assert raw.get("_note"), f"{fixture_path.name} gap fixture must carry a _note field"
    assert not raw.get("_expected_violation")
    data = strip_metadata(raw)
    errors = list(validator.iter_errors(data))
    assert not errors, (
        f"expected gap fixture {fixture_path.name} to PASS schema validation but got: "
        + "; ".join(e.message for e in errors)
    )


def test_system_scope_with_tenant_id_violation_is_scope_discriminator() -> None:
    validator = _validator()
    fixture_path = FIXTURE_DIR / "invalid" / "system-scope-with-tenant-id.json"
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    assert errors, "expected system-scope-with-tenant-id.json to fail validation"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
