"""context/tenant-context/v1 fixture validation (w1-11).

TenantContext is the FIRST worked example of the tolerant-read test
obligation (tests/contract/README.md "Tolerant-read test obligation",
ADR-0012): `unknown-status-tolerant-read.json` carries a `status` value
("archived") not present in the current v1 enum
(active|suspended|terminating). It is schema-INVALID by design (enum
widening = major version bump, ADR-0012) -- the schema-level assertion
below in `test_invalid_fixture_fails` covers that half.

The obligation's OTHER half is this module's job to prove: a
consumer-side handling stub (`resolve_tenant_status()`) that receives
that same unrecognized value and degrades SAFELY to a documented
Fallback branch rather than raising/crashing. This is defense-in-depth
for the old-consumer/new-producer overlap window during a future major
version rollout (README: "not a loophole ... a second, independent
safety net"). `VerificationResult.status` and the envelope's
`de_identification_status` are documented as SUBSEQUENT instances of
this same obligation (README "Worked-example bookkeeping") -- this
module's `resolve_tenant_status()` is the reference shape those two are
expected to mirror, not reinvent (see test_verification_result.py's
`resolve_verification_status()` for the second instance).
"""

from __future__ import annotations

import enum
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
    CONTRACTS_JSON_SCHEMA_DIR / "context" / "tenant-context" / "v1" / "tenant-context.schema.json"
)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "tenant-context"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")

GAP_FIXTURE_NAMES = {"namespace-mismatch.json"}
TOLERANT_READ_FIXTURE_NAME = "unknown-status-tolerant-read.json"
SCHEMA_INVALID_FIXTURES = [p for p in INVALID_FIXTURES if p.name not in GAP_FIXTURE_NAMES]
GAP_FIXTURES = [p for p in INVALID_FIXTURES if p.name in GAP_FIXTURE_NAMES]


def _validator():  # type: ignore[no-untyped-def]
    return build_validator(SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA, ENGINE_ID_SCHEMA])


def test_fixture_inventory_complete() -> None:
    assert len(VALID_FIXTURES) == 2
    assert len(INVALID_FIXTURES) == 6, f"found {[p.name for p in INVALID_FIXTURES]}"
    assert len(SCHEMA_INVALID_FIXTURES) == 5
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
    assert raw.get("_expected_violation"), (
        f"{fixture_path.name} is missing the required _expected_violation metadata field"
    )


@pytest.mark.parametrize("fixture_path", GAP_FIXTURES, ids=lambda p: p.name)
def test_gap_fixture_is_schema_valid_with_note(fixture_path: Path) -> None:
    """namespace-mismatch.json is a PERMANENT gap (schema $comment on
    'namespace' -- the tenant_id<->namespace cross-field invariant is not
    schema-expressible). It must remain schema-VALID and must carry a
    `_note` (not `_expected_violation`) per the fixture metadata
    convention for intentionally schema-valid gap fixtures.
    """
    validator = _validator()
    raw = load_json(fixture_path)
    assert raw.get("_note"), f"{fixture_path.name} gap fixture must carry a _note field"
    assert not raw.get("_expected_violation"), (
        f"{fixture_path.name} is a gap fixture (schema-valid by design) and must not carry "
        "_expected_violation"
    )
    data = strip_metadata(raw)
    errors = list(validator.iter_errors(data))
    assert not errors, (
        f"expected gap fixture {fixture_path.name} to PASS schema validation but got: "
        + "; ".join(e.message for e in errors)
    )


# --------------------------------------------------------------------------
# Tolerant-read worked example (README "Tolerant-read test obligation",
# FIRST instance -- TenantContext.status).
# --------------------------------------------------------------------------


class TenantStatus(enum.Enum):
    """Consumer-side resolved status: Known(value) for a recognized v1 enum
    member, Fallback for anything else (including future/unrecognized
    values). Mirrors the two-branch shape README :154-175 requires --
    "routes to a documented fallback branch, does not raise/crash".
    """

    KNOWN = "known"
    FALLBACK = "fallback"


_KNOWN_STATUS_VALUES = frozenset({"active", "suspended", "terminating"})


def resolve_tenant_status(value: str) -> tuple[TenantStatus, str | None]:
    """Reference tolerant-read consumer stub (ADR-0012 obligation,
    tests/contract/README.md "Tolerant-read test obligation", W2A
    reference -- docs/architecture/data-ownership.md-adjacent consumer
    contract, not itself a W2A deliverable, but the shape a W2A
    TenantContext consumer is expected to implement).

    Returns (TenantStatus.KNOWN, value) for a recognized v1 enum member,
    or (TenantStatus.FALLBACK, value) for any unrecognized value --
    degrading safely (never raising) so a minor-version status addition
    at the producer does not crash an already-deployed consumer during
    the rollout overlap window.
    """
    if value in _KNOWN_STATUS_VALUES:
        return (TenantStatus.KNOWN, value)
    return (TenantStatus.FALLBACK, value)


def test_tolerant_read_stub_resolves_known_status() -> None:
    result, raw = resolve_tenant_status("active")
    assert result is TenantStatus.KNOWN
    assert raw == "active"


def test_tolerant_read_stub_degrades_unknown_status_without_raising() -> None:
    """The core obligation assertion: an unrecognized status value must
    route to Fallback, not raise. Uses the same value the fixture below
    documents as schema-invalid, proving the runtime stub and the schema
    gate are two INDEPENDENT layers (schema rejects it at the wire; the
    consumer stub tolerates it if it ever gets through some other path,
    e.g. an older/newer service version skew).
    """
    fixture_path = FIXTURE_DIR / "invalid" / TOLERANT_READ_FIXTURE_NAME
    data = load_json(fixture_path)
    unknown_value = data["status"]
    assert unknown_value not in _KNOWN_STATUS_VALUES

    result, raw = resolve_tenant_status(unknown_value)  # must not raise
    assert result is TenantStatus.FALLBACK
    assert raw == unknown_value


def test_tolerant_read_fixture_is_schema_invalid_by_design() -> None:
    """The enum-widening half: the unknown-status fixture MUST fail schema
    validation (ADR-0012 enum both-directions-breaking rule) -- this is
    NOT a loophole granting the value schema acceptance, only a runtime
    consumer-side safety net (README explicit "not a free pass").
    """
    validator = _validator()
    fixture_path = FIXTURE_DIR / "invalid" / TOLERANT_READ_FIXTURE_NAME
    raw = load_json(fixture_path)
    data = strip_metadata(raw)
    errors = list(validator.iter_errors(data))
    assert errors, "expected the tolerant-read fixture to fail schema validation"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
