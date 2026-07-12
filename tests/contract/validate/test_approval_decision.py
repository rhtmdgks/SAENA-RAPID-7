"""domain/approval-decision/v1 fixture validation (w1-11)."""

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
    CONTRACTS_JSON_SCHEMA_DIR
    / "domain"
    / "approval-decision"
    / "v1"
    / "approval-decision.schema.json"
)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "approval-decision"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")


def _validator():  # type: ignore[no-untyped-def]
    return build_validator(SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA])


def test_fixture_inventory_complete() -> None:
    assert len(VALID_FIXTURES) == 3
    assert len(INVALID_FIXTURES) == 5


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


def test_h7_dual_approval_pattern_two_instances_share_contract_hash() -> None:
    """Documents/locks the H-7 dual-approval pattern (schema $comment):
    each approver submits ONE ApprovalDecision instance; two required
    approvers = two separate instances sharing the same contract_hash, not
    a multi-approver array inside a single instance.
    """
    approved = load_json(FIXTURE_DIR / "valid" / "approved-single-unit.json")
    second = load_json(FIXTURE_DIR / "valid" / "second-approver-h7-dual.json")
    assert approved["contract_hash"] == second["contract_hash"]
    assert approved["approver_actor_id"] != second["approver_actor_id"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
