"""common/identifiers/v1 fixture validation (w1-11).

This file defines NO root type -- $defs only (see the schema's own
description). Fixtures therefore cannot be validated as top-level
instances of the file the way every other contract's fixtures are;
each fixture instead carries a `_defs_pointer` key naming which
`$defs.<name>` sub-schema its `value` should be validated against
(approved plan §2 "$defs별 wrapper 방식 -- validate 모듈이 pointer
파라미터라이즈").
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from _support import (
    IDENTIFIERS_SCHEMA,
    fixture_pairs,
    load_json,
)
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "common-identifiers"
VALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "valid")
INVALID_FIXTURES = fixture_pairs(FIXTURE_DIR / "invalid")


def _defs_validator() -> tuple[dict[str, Any], Registry]:
    schema = load_json(IDENTIFIERS_SCHEMA)
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    return schema, registry


def _validate_pointer(pointer: str, value: Any) -> list[Any]:
    schema, registry = _defs_validator()
    assert pointer in schema["$defs"], f"$defs.{pointer} does not exist in common/identifiers/v1"
    # Reference the $def by its absolute URI (schema $id + fragment) rather
    # than a bare "#/$defs/..." pointer wrapped in a NEW document -- a new
    # wrapper document with its own $id breaks "#/..." pointer resolution
    # (the pointer would resolve against the wrapper, which has no $defs of
    # its own). Anchoring on the identifiers schema's own $id keeps
    # resolution against the real document registered in `registry`.
    wrapper_schema = {"$ref": f"{schema['$id']}#/$defs/{pointer}"}
    validator = Draft202012Validator(wrapper_schema, registry=registry)
    return list(validator.iter_errors(value))


def test_fixture_inventory_complete() -> None:
    valid_names = [p.name for p in VALID_FIXTURES]
    invalid_names = [p.name for p in INVALID_FIXTURES]
    assert len(VALID_FIXTURES) == 3, f"expected 3 valid fixtures, found {valid_names}"
    assert len(INVALID_FIXTURES) == 6, f"expected 6 invalid fixtures, found {invalid_names}"


@pytest.mark.parametrize("fixture_path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_fixture_pointer_passes(fixture_path: Path) -> None:
    data = load_json(fixture_path)
    errors = _validate_pointer(data["_defs_pointer"], data["value"])
    assert not errors, (
        f"expected {fixture_path.name} ($defs.{data['_defs_pointer']}) to be valid but got: "
        + "; ".join(e.message for e in errors)
    )


@pytest.mark.parametrize("fixture_path", INVALID_FIXTURES, ids=lambda p: p.name)
def test_invalid_fixture_pointer_fails(fixture_path: Path) -> None:
    data = load_json(fixture_path)
    errors = _validate_pointer(data["_defs_pointer"], data["value"])
    pointer = data["_defs_pointer"]
    assert errors, (
        f"expected {fixture_path.name} ($defs.{pointer}) to FAIL validation but it passed"
    )
    assert data.get("_expected_violation"), (
        f"{fixture_path.name} is missing the required _expected_violation metadata field"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
