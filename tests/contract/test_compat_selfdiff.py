"""Bootstrap structural-diff harness for contract compatibility checks (ADR-0012).

ADR-0012 requires a compatibility test with two legs:

  1. N-1 tag example instances must validate against the current schema
     (backward-compat, "does the new schema still accept old instances").
  2. A structural diff between the previous and current schema must
     detect forbidden changes not accompanied by a major version bump:
       - required field added or removed
       - a property's declared type narrowed
       - an enum narrowed OR widened (ADR-0012: both directions are
         breaking for event payloads — narrowing loses values a producer
         may still emit, widening produces forward-incompatible unknown
         values for old consumers) without a major bump

  Full N-1 git-tag wiring (leg 1, tag resolution, registry.json lookup)
  is W1 scope per ADR-0011/0012 ("harness code = testing ownership, but
  git tag / registry.json content = Contracts Steward"). This module
  ships the structural-diff *function* now (testable in isolation, no
  git-tag dependency) plus a self-diff smoke test: the draft envelope
  schema diffed against itself must report zero breaking changes. This
  proves the function is wired correctly ahead of W1's tag-based
  before/after schema loading.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "envelope"
SCHEMA_PATH = FIXTURES_DIR / "draft-envelope.schema.json"


# --------------------------------------------------------------------------
# Structural diff function
# --------------------------------------------------------------------------


def structural_diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Recursively compare two JSON Schema documents (or subschemas) and
    return a list of human-readable breaking-change descriptions.

    Detects (per ADR-0012 event-payload rules, applied conservatively):
      - required-add:   a property added to `required` that was not
                         required before (new mandatory field breaks old
                         producers/consumers that omit it).
      - required-remove: a property removed from `required` — treated as
                          breaking here because dropping a guarantee a
                          consumer already relies on is not detectable as
                          safe without consumer-side knowledge; the single
                          harness (ADR-0012) flags it for human review.
      - type-narrow:    a property's `type` changed such that the new
                         type set is a strict subset of the old one
                         (fewer accepted JSON types than before).
      - enum-change:    an `enum` list gained or lost any value (ADR-0012:
                         both narrowing and widening are breaking).

    Does NOT flag (non-breaking, per ADR-0012 "optional field addition
    = minor"):
      - a new optional property (present in `properties` but absent from
        `required` in both before/after, or newly added to `properties`
        without also being added to `required`).
      - type widening (new type superset of old type set) — permissive,
        flagged nowhere in ADR-0012 as breaking; left non-breaking here.

    This is a *bootstrap* implementation for W0. It walks `properties`,
    `required`, `enum`, and `$defs` recursively. It does not attempt to
    resolve `$ref` across documents or interpret `oneOf`/`anyOf` branch
    semantics beyond recursing into their subschemas positionally — W1
    may need to extend this for full contract coverage (registered as an
    open follow-up, not a silent gap: see tests/contract/README.md).
    """
    violations: list[str] = []
    _diff_node(before, after, path="$", violations=violations)
    return violations


def _as_type_set(type_value: Any) -> set[str]:
    if type_value is None:
        return set()
    if isinstance(type_value, str):
        return {type_value}
    if isinstance(type_value, list):
        return set(type_value)
    return set()


def _diff_node(
    before: dict[str, Any] | Any,
    after: dict[str, Any] | Any,
    path: str,
    violations: list[str],
) -> None:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return

    # required-add / required-remove
    before_required = set(before.get("required", []))
    after_required = set(after.get("required", []))
    for added in sorted(after_required - before_required):
        violations.append(f"{path}: required-add '{added}'")
    for removed in sorted(before_required - after_required):
        violations.append(f"{path}: required-remove '{removed}'")

    # type-narrow
    before_types = _as_type_set(before.get("type"))
    after_types = _as_type_set(after.get("type"))
    if before_types and after_types and not before_types.issubset(after_types):
        lost = before_types - after_types
        if lost:
            violations.append(
                f"{path}: type-narrow lost {sorted(lost)} (before={sorted(before_types)}, "
                f"after={sorted(after_types)})"
            )

    # enum-change (narrow or widen — both breaking per ADR-0012)
    before_enum = before.get("enum")
    after_enum = after.get("enum")
    if before_enum is not None or after_enum is not None:
        before_enum_set = set(before_enum or [])
        after_enum_set = set(after_enum or [])
        if before_enum_set != after_enum_set:
            narrowed = before_enum_set - after_enum_set
            widened = after_enum_set - before_enum_set
            detail = []
            if narrowed:
                detail.append(f"narrowed(removed)={sorted(narrowed)}")
            if widened:
                detail.append(f"widened(added)={sorted(widened)}")
            violations.append(f"{path}: enum-change {' '.join(detail)}")

    # Recurse into properties (shared keys only — new/removed *properties*
    # without a required-add/remove are non-breaking additions/removals
    # of optional fields and are intentionally not flagged here).
    before_props = before.get("properties", {})
    after_props = after.get("properties", {})
    if isinstance(before_props, dict) and isinstance(after_props, dict):
        for key in sorted(set(before_props) & set(after_props)):
            _diff_node(before_props[key], after_props[key], f"{path}.properties.{key}", violations)

    # Recurse into $defs
    before_defs = before.get("$defs", {})
    after_defs = after.get("$defs", {})
    if isinstance(before_defs, dict) and isinstance(after_defs, dict):
        for key in sorted(set(before_defs) & set(after_defs)):
            _diff_node(before_defs[key], after_defs[key], f"{path}.$defs.{key}", violations)

    # Recurse into oneOf/anyOf/allOf branches positionally.
    for combiner in ("oneOf", "anyOf", "allOf"):
        before_branches = before.get(combiner)
        after_branches = after.get(combiner)
        if isinstance(before_branches, list) and isinstance(after_branches, list):
            for idx, (b_branch, a_branch) in enumerate(
                zip(before_branches, after_branches, strict=False)
            ):
                _diff_node(b_branch, a_branch, f"{path}.{combiner}[{idx}]", violations)


# --------------------------------------------------------------------------
# Self-diff bootstrap test: draft schema against itself must be clean.
# --------------------------------------------------------------------------


def test_draft_schema_selfdiff_is_clean() -> None:
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
