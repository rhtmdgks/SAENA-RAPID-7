"""common/problem-detail/v1 fixture validation (w1-11)."""

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
    CONTRACTS_JSON_SCHEMA_DIR / "common" / "problem-detail" / "v1" / "problem-detail.schema.json"
)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "problem-detail"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")


def test_fixture_inventory_complete() -> None:
    assert len(VALID_FIXTURES) == 1
    assert len(INVALID_FIXTURES) == 1


@pytest.mark.parametrize("fixture_path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_fixture_passes(fixture_path: Path) -> None:
    validator = build_validator(SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA])
    data = strip_metadata(load_json(fixture_path))
    errors = list(validator.iter_errors(data))
    assert not errors, f"expected {fixture_path.name} to be valid: {[e.message for e in errors]}"


@pytest.mark.parametrize("fixture_path", INVALID_FIXTURES, ids=lambda p: p.name)
def test_invalid_fixture_fails(fixture_path: Path) -> None:
    validator = build_validator(SCHEMA_PATH, extra_resource_paths=[IDENTIFIERS_SCHEMA])
    raw = load_json(fixture_path)
    data = strip_metadata(raw)
    errors = list(validator.iter_errors(data))
    assert errors, f"expected {fixture_path.name} to FAIL validation but it passed"
    assert raw.get("_expected_violation")
    messages = " ".join(e.message for e in errors)
    assert "title" in messages, f"expected the missing-'title' violation, got: {messages}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
