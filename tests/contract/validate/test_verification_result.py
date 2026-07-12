"""domain/verification-result/v1 fixture validation (w1-11).

VerificationResult.status is the SECOND worked instance of the
tolerant-read test obligation (tests/contract/README.md
"Worked-example bookkeeping (corrected, w1-03)" -- TenantContext.status
is first, this is a subsequent instance of the same obligation, not a
separate one; the fixture shape and stub degrade-safely assertion are
established once and repeated here, not reinvented). See
test_tenant_context.py::resolve_tenant_status for the reference shape.
VerificationResult's enum currently has no genuinely "unknown v1 value"
gap the way TenantContext's does (status is closed two-value
passed|failed with no historical third value on record) -- the stub
below is still provided, exercised against a synthetic out-of-catalog
value, to prove the obligation's mechanics generalize beyond the first
worked example, per the README's "each must carry its own tolerant-read
fixture and stub" requirement.
"""

from __future__ import annotations

import enum
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

SCHEMA_PATH = (
    CONTRACTS_JSON_SCHEMA_DIR
    / "domain"
    / "verification-result"
    / "v1"
    / "verification-result.schema.json"
)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "verification-result"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")


def _validator():  # type: ignore[no-untyped-def]
    return build_validator(
        SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA, ERROR_DETAIL_SCHEMA]
    )


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


def test_failed_without_failures_violation_references_failures() -> None:
    validator = _validator()
    fixture_path = FIXTURE_DIR / "invalid" / "failed-without-failures.json"
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    messages = " ".join(e.message for e in errors)
    assert "failures" in messages, f"expected a failures-referencing error, got: {messages}"


def test_passed_with_failures_violation_references_failures() -> None:
    validator = _validator()
    fixture_path = FIXTURE_DIR / "invalid" / "passed-with-failures.json"
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    messages = " ".join(e.message for e in errors)
    assert "failures" in messages, f"expected a failures-referencing error, got: {messages}"


# --------------------------------------------------------------------------
# Tolerant-read obligation, second instance (README bookkeeping).
# --------------------------------------------------------------------------


class VerificationStatus(enum.Enum):
    KNOWN = "known"
    FALLBACK = "fallback"


_KNOWN_VERIFICATION_STATUS_VALUES = frozenset({"passed", "failed"})


def resolve_verification_status(value: str) -> tuple[VerificationStatus, str | None]:
    """Second instance of the tolerant-read consumer stub pattern
    (mirrors test_tenant_context.py::resolve_tenant_status shape exactly
    -- README requires the pattern be repeated, not reinvented).
    """
    if value in _KNOWN_VERIFICATION_STATUS_VALUES:
        return (VerificationStatus.KNOWN, value)
    return (VerificationStatus.FALLBACK, value)


def test_tolerant_read_stub_resolves_known_status() -> None:
    result, raw = resolve_verification_status("passed")
    assert result is VerificationStatus.KNOWN
    assert raw == "passed"


def test_tolerant_read_stub_degrades_unknown_status_without_raising() -> None:
    """No historical 'unknown status' fixture exists for this two-value
    closed enum (unlike TenantContext) -- exercised against a synthetic
    out-of-catalog value ('conditional_pass', explicitly excluded from
    v1 per the schema's own $comment) to prove the same degrade-safely
    mechanics apply here too.
    """
    result, raw = resolve_verification_status("conditional_pass")  # must not raise
    assert result is VerificationStatus.FALLBACK
    assert raw == "conditional_pass"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
