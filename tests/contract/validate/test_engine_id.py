"""common/engine-id/v1 fixture validation (w1-11).

Fixtures wrap the enum value under a `value` key (no root object type --
this contract's root is a bare string enum), validated against the
schema's root type directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _support import ENGINE_ID_SCHEMA, build_validator, fixture_pairs, load_json

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "engine-id"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")


def test_fixture_inventory_complete() -> None:
    assert len(VALID_FIXTURES) == 1
    assert len(INVALID_FIXTURES) == 1


@pytest.mark.parametrize("fixture_path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_fixture_passes(fixture_path: Path) -> None:
    validator = build_validator(ENGINE_ID_SCHEMA)
    data = load_json(fixture_path)
    errors = list(validator.iter_errors(data["value"]))
    assert not errors, f"expected {fixture_path.name} to be valid: {[e.message for e in errors]}"


@pytest.mark.parametrize("fixture_path", INVALID_FIXTURES, ids=lambda p: p.name)
def test_invalid_fixture_fails(fixture_path: Path) -> None:
    validator = build_validator(ENGINE_ID_SCHEMA)
    data = load_json(fixture_path)
    errors = list(validator.iter_errors(data["value"]))
    assert errors, f"expected {fixture_path.name} to FAIL validation but it passed"
    assert data.get("_expected_violation")
    messages = " ".join(e.message for e in errors)
    assert "chatgpt-search" in messages, (
        f"expected the enum-violation error message to reference the closed enum, got: {messages}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
