"""Structural-diff harness for contract compatibility checks (ADR-0012).

ADR-0012 requires a compatibility test with two legs:

  1. N-1 tag example instances must validate against the current schema
     (backward-compat, "does the new schema still accept old instances").
  2. A structural diff between the previous and current schema must
     detect forbidden changes not accompanied by a major version bump:
       - required field added or removed
       - a property's declared type narrowed
       - an enum narrowed OR widened (ADR-0012: both directions are
         breaking for event payloads -- narrowing loses values a producer
         may still emit, widening produces forward-incompatible unknown
         values for old consumers) without a major bump

  `structural_diff()` itself now lives in `tests/contract/harness/diff.py`
  (MOVED there, not copied, in w1-10 -- see that module's docstring for
  the full W1 extension list: items recursion, within-file $ref
  resolution, const-change, cross-file $ref comparison, pattern-change).
  This module keeps the W0 self-diff smoke test and the original unit
  tests, now exercising the moved function via import; full N-1 git-tag
  wiring lives in `tests/contract/compat/test_n1_compat.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.diff import structural_diff

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT
    / "packages/contracts/json-schema/envelope/event-envelope/v1/event-envelope.schema.json"
)


# --------------------------------------------------------------------------
# Self-diff bootstrap test: authoritative envelope against itself must be clean.
# --------------------------------------------------------------------------


def test_envelope_schema_selfdiff_is_clean() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    violations = structural_diff(schema, schema)
    assert violations == [], f"self-diff must be empty but found: {violations}"


# --------------------------------------------------------------------------
# Unit tests of the diff function on synthetic before/after dicts.
# --------------------------------------------------------------------------


def test_required_add_is_detected() -> None:
    before = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    after = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a", "b"],
    }
    violations = structural_diff(before, after)
    assert any("required-add 'b'" in v for v in violations), violations


def test_required_remove_is_detected() -> None:
    before = {"type": "object", "properties": {"a": {}, "b": {}}, "required": ["a", "b"]}
    after = {"type": "object", "properties": {"a": {}, "b": {}}, "required": ["a"]}
    violations = structural_diff(before, after)
    assert any("required-remove 'b'" in v for v in violations), violations


def test_enum_widen_is_detected() -> None:
    before = {"type": "string", "enum": ["chatgpt-search"]}
    after = {"type": "string", "enum": ["chatgpt-search", "google-ai-overviews"]}
    violations = structural_diff(before, after)
    assert any("enum-change" in v and "widened" in v for v in violations), violations


def test_enum_narrow_is_detected() -> None:
    before = {"type": "string", "enum": ["k_anonymized", "suppressed", "pending_review"]}
    after = {"type": "string", "enum": ["k_anonymized", "suppressed"]}
    violations = structural_diff(before, after)
    assert any("enum-change" in v and "narrowed" in v for v in violations), violations


def test_type_narrow_is_detected() -> None:
    before = {"type": ["string", "null"]}
    after = {"type": "string"}
    violations = structural_diff(before, after)
    assert any("type-narrow" in v for v in violations), violations


def test_optional_add_is_not_breaking() -> None:
    """Adding a new property WITHOUT adding it to `required` is a minor,
    non-breaking change per ADR-0012 ("optional 필드 추가 = minor").
    """
    before = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    after = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a"],
    }
    violations = structural_diff(before, after)
    assert violations == [], f"expected no breaking changes but found: {violations}"


def test_no_change_is_clean() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string", "enum": ["x", "y"]}},
        "required": ["a"],
    }
    violations = structural_diff(schema, json.loads(json.dumps(schema)))
    assert violations == []


def test_nested_property_enum_change_is_detected() -> None:
    before = {
        "type": "object",
        "properties": {
            "de_identification_status": {
                "type": "string",
                "enum": ["k_anonymized", "suppressed", "pending_review"],
            }
        },
    }
    after = {
        "type": "object",
        "properties": {
            "de_identification_status": {
                "type": "string",
                "enum": ["k_anonymized", "suppressed"],
            }
        },
    }
    violations = structural_diff(before, after)
    assert any("de_identification_status" in v and "narrowed" in v for v in violations), violations
