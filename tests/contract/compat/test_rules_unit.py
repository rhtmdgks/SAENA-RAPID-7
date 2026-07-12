"""Synthetic unit tests for harness.rules.judge() (ADR-0012 dual policy).

These tests use hand-built RegistryEntry objects and hand-built
before/after schema bytes / structural findings -- no real
packages/contracts schema files or git tags required. This lets the
judgment logic be fully unit-tested ahead of any real contract landing
(W1 dependency DAG: w1-10 harness precedes w1-04..08 schema authoring).
"""

from __future__ import annotations

import json

import pytest
from harness.registry import RegistryEntry
from harness.rules import judge


def _entry(
    compat_class: str,
    major: int = 1,
    signed: bool = False,
    name: str = "synthetic-contract",
) -> RegistryEntry:
    return RegistryEntry(
        name=name,
        catalog_name="SyntheticContract",
        category="domain",
        compat_class=compat_class,
        signed=signed,
        format="json-schema",
        major=major,
        full_version=f"{major}.0.0",
        id_=f"https://schemas.the-saena.ai/domain/{name}/v{major}/{name}.schema.json",
        owner="contracts-steward",
        status="active",
        frozen_authority_adr="ADR-0013" if compat_class == "frozen" else None,
    )


def _bytes(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


# --------------------------------------------------------------------------
# closed
# --------------------------------------------------------------------------


def test_closed_optional_add_without_major_bump_is_breaking() -> None:
    entry = _entry("closed")
    old = _bytes({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    new = _bytes(
        {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a"],
        }
    )
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=[],
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "breaking", result.reasons


def test_closed_change_with_major_bump_passes() -> None:
    entry = _entry("closed", major=2)
    old = _bytes({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    new = _bytes(
        {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a"],
        }
    )
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=[],
        old_major=1,
        new_major=2,
    )
    assert result.verdict == "pass", result.reasons


def test_closed_no_change_passes_without_major_bump() -> None:
    entry = _entry("closed")
    schema = _bytes({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    result = judge(
        entry=entry,
        old_schema_bytes=schema,
        new_schema_bytes=schema,
        structural_findings=[],
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "pass", result.reasons


def test_closed_key_order_does_not_matter_canonical_compare() -> None:
    """Canonical-JSON (sort_keys) comparison means byte-order differences
    alone must not be treated as a change.
    """
    entry = _entry("closed")
    old = _bytes({"required": ["a"], "type": "object", "properties": {"a": {"type": "string"}}})
    new = _bytes({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=[],
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "pass", result.reasons


# --------------------------------------------------------------------------
# frozen
# --------------------------------------------------------------------------


def test_frozen_change_with_major_bump_still_fails() -> None:
    entry = _entry("frozen", major=2)
    old = _bytes({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    new = _bytes(
        {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a"],
        }
    )
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=[],
        old_major=1,
        new_major=2,
    )
    assert result.verdict == "fail", result.reasons
    assert any("new ADR" in reason for reason in result.reasons)


def test_frozen_no_change_passes() -> None:
    entry = _entry("frozen")
    schema = _bytes({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    result = judge(
        entry=entry,
        old_schema_bytes=schema,
        new_schema_bytes=schema,
        structural_findings=[],
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "pass", result.reasons


# --------------------------------------------------------------------------
# open
# --------------------------------------------------------------------------


def test_open_enum_widen_without_major_bump_fails() -> None:
    entry = _entry("open")
    old = _bytes({"type": "string", "enum": ["a"]})
    new = _bytes({"type": "string", "enum": ["a", "b"]})
    findings = ["$: enum-change widened(added)=['b']"]
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=findings,
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "breaking", result.reasons


def test_open_enum_widen_with_major_bump_passes() -> None:
    entry = _entry("open", major=2)
    old = _bytes({"type": "string", "enum": ["a"]})
    new = _bytes({"type": "string", "enum": ["a", "b"]})
    findings = ["$: enum-change widened(added)=['b']"]
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=findings,
        old_major=1,
        new_major=2,
    )
    assert result.verdict == "pass", result.reasons


def test_open_optional_add_passes_without_major_bump() -> None:
    entry = _entry("open")
    old = _bytes({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
    new = _bytes(
        {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a"],
        }
    )
    # structural_diff() does not emit a finding for plain optional-property
    # additions -- empty findings list is the real-world signal.
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=[],
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "pass", result.reasons


def test_open_required_add_without_major_bump_fails() -> None:
    entry = _entry("open")
    old = _bytes({"type": "object", "properties": {"a": {}}, "required": ["a"]})
    new = _bytes({"type": "object", "properties": {"a": {}, "b": {}}, "required": ["a", "b"]})
    findings = ["$: required-add 'b'"]
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=findings,
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "breaking", result.reasons


def test_open_pattern_change_without_major_bump_fails() -> None:
    """Ruling R5: pattern change is breaking in both directions."""
    entry = _entry("open")
    old = _bytes({"type": "string", "pattern": "^a$"})
    new = _bytes({"type": "string", "pattern": "^b$"})
    findings = ["$: pattern-changed before='^a$' after='^b$'"]
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=findings,
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "breaking", result.reasons


def test_open_const_change_without_major_bump_fails() -> None:
    entry = _entry("open")
    old = _bytes({"const": "a"})
    new = _bytes({"const": "b"})
    findings = ["$: const-change before='a' after='b'"]
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=findings,
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "breaking", result.reasons


def test_open_external_ref_change_without_major_bump_fails() -> None:
    entry = _entry("open")
    old = _bytes(
        {"$ref": "https://schemas.the-saena.ai/common/identifiers/v1/identifiers.schema.json"}
    )
    new = _bytes(
        {"$ref": "https://schemas.the-saena.ai/common/identifiers/v2/identifiers.schema.json"}
    )
    findings = [
        "$: external-ref-changed before='https://schemas.the-saena.ai/common/identifiers/v1/"
        "identifiers.schema.json' after='https://schemas.the-saena.ai/common/identifiers/v2/"
        "identifiers.schema.json'"
    ]
    result = judge(
        entry=entry,
        old_schema_bytes=old,
        new_schema_bytes=new,
        structural_findings=findings,
        old_major=1,
        new_major=1,
    )
    assert result.verdict == "breaking", result.reasons


# --------------------------------------------------------------------------
# Defensive branch: unknown compat_class
# --------------------------------------------------------------------------


def test_unknown_compat_class_raises() -> None:
    """registry.schema.json's compat_class enum only allows
    closed|open|frozen, so this branch is defense-in-depth against a
    future enum-widening bug rather than a reachable real-world state --
    still worth locking down since judge() is the sole compat-judgment
    implementation (ADR-0012 single-harness rule) and a silent
    fall-through here would be worse than a loud ValueError.
    """
    entry = _entry("open")
    object.__setattr__(entry, "compat_class", "bogus")
    with pytest.raises(ValueError, match="unknown compat_class"):
        judge(
            entry=entry,
            old_schema_bytes=_bytes({}),
            new_schema_bytes=_bytes({}),
            structural_findings=[],
            old_major=1,
            new_major=1,
        )
