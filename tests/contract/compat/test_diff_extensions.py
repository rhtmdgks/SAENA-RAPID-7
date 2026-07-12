"""Unit tests for the W1 extensions to harness.diff.structural_diff()
(items recursion, within-file $ref + cycle guard, const-change,
pattern-changed, external-ref-changed). See harness/diff.py module
docstring for the (a)-(e) extension list this file exercises.
"""

from __future__ import annotations

from harness.diff import structural_diff

# --------------------------------------------------------------------------
# (a) items recursion
# --------------------------------------------------------------------------


def test_items_enum_change_is_detected() -> None:
    before = {
        "type": "array",
        "items": {"type": "string", "enum": ["a", "b", "c"]},
    }
    after = {
        "type": "array",
        "items": {"type": "string", "enum": ["a", "b"]},
    }
    violations = structural_diff(before, after)
    assert any(".items" in v and "narrowed" in v for v in violations), violations


def test_items_required_add_is_detected() -> None:
    before = {
        "type": "array",
        "items": {"type": "object", "properties": {"a": {}}, "required": ["a"]},
    }
    after = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"a": {}, "b": {}},
            "required": ["a", "b"],
        },
    }
    violations = structural_diff(before, after)
    assert any(".items" in v and "required-add 'b'" in v for v in violations), violations


# --------------------------------------------------------------------------
# (b) within-file $ref resolution + cycle guard
# --------------------------------------------------------------------------


def test_ref_indirected_enum_change_is_detected() -> None:
    before = {
        "$defs": {"Status": {"type": "string", "enum": ["a", "b"]}},
        "type": "object",
        "properties": {"status": {"$ref": "#/$defs/Status"}},
    }
    after = {
        "$defs": {"Status": {"type": "string", "enum": ["a"]}},
        "type": "object",
        "properties": {"status": {"$ref": "#/$defs/Status"}},
    }
    violations = structural_diff(before, after)
    assert any("narrowed" in v for v in violations), violations


def test_defs_cycle_guard_terminates() -> None:
    """A self-referential $defs structure must not cause infinite
    recursion; the diff must simply terminate (possibly with findings,
    possibly clean) rather than hang or raise RecursionError.
    """
    before = {
        "$defs": {"Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}},
        "$ref": "#/$defs/Node",
    }
    after = {
        "$defs": {"Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}},
        "$ref": "#/$defs/Node",
    }
    violations = structural_diff(before, after)
    assert violations == []


def test_defs_cycle_guard_terminates_with_a_real_change() -> None:
    before = {
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {"child": {"$ref": "#/$defs/Node"}, "value": {"type": "string"}},
                "required": ["value"],
            }
        },
        "$ref": "#/$defs/Node",
    }
    after = {
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {"child": {"$ref": "#/$defs/Node"}, "value": {"type": "string"}},
                "required": [],
            }
        },
        "$ref": "#/$defs/Node",
    }
    violations = structural_diff(before, after)
    assert any("required-remove 'value'" in v for v in violations), violations


# --------------------------------------------------------------------------
# (c) const-change
# --------------------------------------------------------------------------


def test_const_change_is_detected() -> None:
    before = {"type": "string", "const": "chatgpt-search"}
    after = {"type": "string", "const": "google-ai-overviews"}
    violations = structural_diff(before, after)
    assert any("const-change" in v for v in violations), violations


def test_const_added_is_detected() -> None:
    before = {"type": "string"}
    after = {"type": "string", "const": "chatgpt-search"}
    violations = structural_diff(before, after)
    assert any("const-change" in v for v in violations), violations


def test_const_unchanged_is_clean() -> None:
    before = {"type": "string", "const": "chatgpt-search"}
    after = {"type": "string", "const": "chatgpt-search"}
    violations = structural_diff(before, after)
    assert violations == []


# --------------------------------------------------------------------------
# (e) pattern-changed (both directions, ruling R5)
# --------------------------------------------------------------------------


def test_pattern_added_is_detected() -> None:
    before = {"type": "string"}
    after = {"type": "string", "pattern": "^[a-z]+$"}
    violations = structural_diff(before, after)
    assert any("pattern-changed" in v for v in violations), violations


def test_pattern_removed_is_detected() -> None:
    before = {"type": "string", "pattern": "^[a-z]+$"}
    after = {"type": "string"}
    violations = structural_diff(before, after)
    assert any("pattern-changed" in v for v in violations), violations


def test_pattern_changed_value_is_detected() -> None:
    before = {"type": "string", "pattern": "^[a-z]+$"}
    after = {"type": "string", "pattern": "^[0-9]+$"}
    violations = structural_diff(before, after)
    assert any("pattern-changed" in v for v in violations), violations


def test_pattern_unchanged_is_clean() -> None:
    before = {"type": "string", "pattern": "^[a-z]+$"}
    after = {"type": "string", "pattern": "^[a-z]+$"}
    violations = structural_diff(before, after)
    assert violations == []


# --------------------------------------------------------------------------
# (d) external-ref-changed (shallow cross-file string comparison, R3)
# --------------------------------------------------------------------------


def test_external_ref_uri_change_is_detected() -> None:
    before = {
        "type": "object",
        "properties": {
            "engine_id": {
                "$ref": "https://schemas.the-saena.ai/common/engine-id/v1/engine-id.schema.json"
            }
        },
    }
    after = {
        "type": "object",
        "properties": {
            "engine_id": {
                "$ref": "https://schemas.the-saena.ai/common/engine-id/v2/engine-id.schema.json"
            }
        },
    }
    violations = structural_diff(before, after)
    assert any("external-ref-changed" in v for v in violations), violations


def test_external_ref_unchanged_is_clean() -> None:
    ref = "https://schemas.the-saena.ai/common/engine-id/v1/engine-id.schema.json"
    before = {"type": "object", "properties": {"engine_id": {"$ref": ref}}}
    after = {"type": "object", "properties": {"engine_id": {"$ref": ref}}}
    violations = structural_diff(before, after)
    assert violations == []


def test_external_ref_does_not_descend_further() -> None:
    """An external $ref node stops descent -- no attempt to structurally
    compare "into" it (that is the referenced document's own compat
    check's job, ruling R3). Confirm no spurious findings appear beyond
    the external-ref-changed one itself even if other keys are present.
    """
    before = {
        "$ref": "https://schemas.the-saena.ai/common/identifiers/v1/identifiers.schema.json",
        "required": ["a"],
    }
    after = {
        "$ref": "https://schemas.the-saena.ai/common/identifiers/v1/identifiers.schema.json",
        "required": ["a", "b"],
    }
    violations = structural_diff(before, after)
    assert violations == []


# --------------------------------------------------------------------------
# Edge cases: type_value shapes, unresolvable internal $ref, non-dict
# branch entries.
# --------------------------------------------------------------------------


def test_as_type_set_handles_non_string_non_list_type_value() -> None:
    """A `type` keyword value that is neither a string nor a list (e.g. an
    already-malformed schema) must not crash the diff -- it degrades to
    "no type information" (empty set) rather than raising, since a
    malformed `type` value is a schema-authoring problem caught elsewhere
    (metaschema check), not this diff function's job.
    """
    before = {"type": 123}
    after = {"type": 123}
    violations = structural_diff(before, after)
    assert violations == []


def test_unresolvable_internal_ref_is_left_as_is() -> None:
    """A `#/$defs/Missing` ref that does not resolve to anything in the
    document must not raise -- the node is compared as-is (still a dict
    containing just `$ref`), which is a no-op diff since both sides are
    identically unresolvable.
    """
    before = {"properties": {"a": {"$ref": "#/$defs/Missing"}}}
    after = {"properties": {"a": {"$ref": "#/$defs/Missing"}}}
    violations = structural_diff(before, after)
    assert violations == []


def test_unresolvable_internal_ref_partial_path_is_left_as_is() -> None:
    """A ref pointing partway into a real structure but hitting a missing
    key partway through (`_resolve_internal_ref` returns None) is handled
    the same way -- no crash, node compared as-is.
    """
    before = {"$defs": {"A": {"type": "string"}}, "properties": {"a": {"$ref": "#/$defs/A/nope"}}}
    after = {"$defs": {"A": {"type": "string"}}, "properties": {"a": {"$ref": "#/$defs/A/nope"}}}
    violations = structural_diff(before, after)
    assert violations == []


def test_non_dict_branch_entry_in_oneof_is_skipped_without_crashing() -> None:
    """A oneOf branch that is not a dict (malformed schema, e.g. `true` as
    a branch) must not crash the recursive diff -- _diff_node's leading
    isinstance guard simply returns without comparing it further.
    """
    before = {"oneOf": [True, {"type": "string"}]}
    after = {"oneOf": [True, {"type": "string", "enum": ["a"]}]}
    violations = structural_diff(before, after)
    # The malformed (non-dict) branch produces no findings by itself; the
    # real dict branch's enum addition is still detected.
    assert any("enum-change" in v for v in violations), violations
