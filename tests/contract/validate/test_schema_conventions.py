"""Repo-wide JSON Schema conventions lint (w1-11, approved plan §2 deliverable 2).

Applies to every `*.schema.json` file under `packages/contracts/**`
(ADR-0011 conventions):

  - `$schema` is the FIRST key in the top-level object (object_pairs_hook,
    order-preserving raw parse -- json.loads default dict already
    preserves insertion order in CPython 3.7+, but we use
    object_pairs_hook explicitly per the plan's own wording so the
    intent is unambiguous and independent of that implementation detail).
  - `$id` <-> on-disk path is 1:1 (ADR-0011 $id scheme).
  - `$id`'s category path segment matches the file's actual category
    directory segment.
  - closed-class contracts (hardcoded approved list, $comment notes the
    registry-driven future) have `additionalProperties: false` at the
    schema root.
  - every cross-file `$ref` is relative (never absolute `https://`),
    `/vN/`-pinned, and targets only the `common/` category (+ the
    `context/tenant-context` -> `common/engine-id` exception is already
    common-category, so no special-case needed -- context files may only
    $ref common/, not other context/domain/event files, per this
    catalog's actual usage).
"""

from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pytest

CONTRACTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "packages" / "contracts"
JSON_SCHEMA_DIR = CONTRACTS_DIR / "json-schema"

ALL_SCHEMA_FILES = sorted(JSON_SCHEMA_DIR.glob("**/*.schema.json"))

_ID_PATH_PATTERN = re.compile(
    r"^https://schemas\.the-saena\.ai/"
    r"(?P<category>envelope|context|domain|event|common)/"
    r"(?P<name>[a-z0-9-]+)/"
    r"v(?P<major>[0-9]+)/"
    r"(?P<filename>[a-z0-9-]+)\.schema\.json$"
)

# Matches BOTH shapes actually used in this catalog:
#   (a) descending from another category into common/, e.g.
#       "../../../common/identifiers/v1/identifiers.schema.json" (3 levels
#       up from <category>/<name>/v1/ to json-schema/, then into common/).
#   (b) a same-category sideways ref from within common/ itself, e.g.
#       "../../identifiers/v1/identifiers.schema.json" (2 levels up from
#       common/problem-detail/v1/ to common/, then into identifiers/).
# Both forms are /vN/-pinned and ultimately resolve to a common/ file --
# the shared invariant this lint enforces is "the LAST directory segment
# before v{N} is a common/-category schema", not a fixed relative depth.
_RELATIVE_REF_WITH_VERSION_PATTERN = re.compile(
    r"^(\.\./)+(common/)?[a-z0-9-]+/v[0-9]+/[a-z0-9-]+\.schema\.json(#.*)?$"
)

# Approved closed-class contract list (approved plan §5 acceptance matrix +
# §2 field table `class` column). Hardcoded here per the plan's own
# instruction ("hardcode the approved closed list w/ registry-future
# $comment") -- $comment: once packages/contracts/registry.json carries
# real entries with a compat_class field (w1-15), this list SHOULD be
# replaced with a read from the registry (same deferred-to-registry pattern
# already used by justfile's codegen recipe OPEN_CONTRACTS list). Until
# then, this list is the single source of truth for this lint and must be
# kept in sync with the registry.json entries as they land.
#
# Object-rooted closed contracts (additionalProperties:false at root is
# the actual closing mechanism -- excludes common/engine-id, which is
# closed but root type:string, checked separately below).
CLOSED_CLASS_SCHEMA_RELPATHS: frozenset[str] = frozenset(
    {
        "common/error-detail/v1/error-detail.schema.json",
        "common/problem-detail/v1/problem-detail.schema.json",
        "context/tenant-context/v1/tenant-context.schema.json",
        "context/actor-context/v1/actor-context.schema.json",
        "context/run-context-experiment/v1/run-context-experiment.schema.json",
        "domain/change-plan/v1/change-plan.schema.json",
        "domain/approval-decision/v1/approval-decision.schema.json",
        "domain/source-snapshot/v1/source-snapshot.schema.json",
        "domain/patch-artifact/v1/patch-artifact.schema.json",
        "domain/audit-event/v1/audit-event.schema.json",
    }
)

# common/engine-id/v1 is compat_class:closed (per its own $comment) but its
# root type is a bare string enum, not an object -- additionalProperties
# does not apply to a string schema. Its closing mechanism is the `enum`
# array itself (single value in v1); checked by a dedicated test below
# rather than folded into the additionalProperties:false check.
ENUM_CLOSED_SCHEMA_RELPATHS: frozenset[str] = frozenset(
    {"common/engine-id/v1/engine-id.schema.json"}
)

# common/identifiers/v1 is compat_class:closed per its own $comment but has
# NO root type at all ($defs-only reuse surface, "no additionalProperties
# root to seal since there is no root object") -- explicitly excluded from
# the additionalProperties:false root check, not silently missed.
DEFS_ONLY_CLOSED_SCHEMA_RELPATHS: frozenset[str] = frozenset(
    {"common/identifiers/v1/identifiers.schema.json"}
)

# event-envelope is frozen (not "closed"), and its root uses `oneOf` over
# 3 branches, each branch closed via `unevaluatedProperties: false` (not a
# root-level `additionalProperties: false`) -- excluded from the
# straightforward root-key check, verified separately below.
FROZEN_ONE_OF_UNEVALUATED_RELPATHS: frozenset[str] = frozenset(
    {"envelope/event-envelope/v1/event-envelope.schema.json"}
)


def _relpath(schema_path: Path) -> str:
    return str(schema_path.relative_to(JSON_SCHEMA_DIR)).replace("\\", "/")


def _load_ordered(schema_path: Path) -> OrderedDict[str, Any]:
    return json.loads(schema_path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def test_at_least_one_schema_file_found() -> None:
    """Meta-test: this suite is worthless if the glob silently matches
    zero files (e.g. a path typo) -- assert a floor matching the catalog
    size (25 P0 schema files as of this unit's authoring; see
    approved plan §2 table row count + common 4 + envelope 1).
    """
    assert len(ALL_SCHEMA_FILES) >= 24, (
        f"expected at least 24 *.schema.json files under {JSON_SCHEMA_DIR}, "
        f"found {len(ALL_SCHEMA_FILES)}"
    )


@pytest.mark.parametrize("schema_path", ALL_SCHEMA_FILES, ids=_relpath)
def test_schema_key_is_first(schema_path: Path) -> None:
    document = _load_ordered(schema_path)
    keys = list(document.keys())
    assert keys, f"{_relpath(schema_path)}: empty document"
    assert keys[0] == "$schema", (
        f"{_relpath(schema_path)}: expected '$schema' as the first key, got {keys[0]!r} "
        f"(full key order: {keys})"
    )


@pytest.mark.parametrize("schema_path", ALL_SCHEMA_FILES, ids=_relpath)
def test_schema_dialect_is_2020_12(schema_path: Path) -> None:
    document = _load_ordered(schema_path)
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize("schema_path", ALL_SCHEMA_FILES, ids=_relpath)
def test_id_matches_pattern_and_on_disk_path(schema_path: Path) -> None:
    document = _load_ordered(schema_path)
    schema_id = document.get("$id")
    assert schema_id, f"{_relpath(schema_path)}: missing $id"

    match = _ID_PATH_PATTERN.match(schema_id)
    assert match is not None, (
        f"{_relpath(schema_path)}: $id {schema_id!r} does not match ADR-0011 pattern"
    )

    relpath = _relpath(schema_path)
    expected_relpath = (
        f"{match.group('category')}/{match.group('name')}/v{match.group('major')}/"
        f"{match.group('filename')}.schema.json"
    )
    assert relpath == expected_relpath, (
        f"$id path does not 1:1-map to the on-disk file: $id implies {expected_relpath!r}, "
        f"actual path is {relpath!r}"
    )


@pytest.mark.parametrize("schema_path", ALL_SCHEMA_FILES, ids=_relpath)
def test_id_category_segment_matches_directory_category(schema_path: Path) -> None:
    document = _load_ordered(schema_path)
    schema_id = document["$id"]
    match = _ID_PATH_PATTERN.match(schema_id)
    assert match is not None

    relpath = _relpath(schema_path)
    actual_category = relpath.split("/", 1)[0]
    assert match.group("category") == actual_category, (
        f"{relpath}: $id category segment {match.group('category')!r} != "
        f"directory category {actual_category!r}"
    )


@pytest.mark.parametrize(
    "relpath", sorted(CLOSED_CLASS_SCHEMA_RELPATHS), ids=sorted(CLOSED_CLASS_SCHEMA_RELPATHS)
)
def test_closed_class_contract_has_additional_properties_false_at_root(relpath: str) -> None:
    schema_path = JSON_SCHEMA_DIR / relpath
    assert schema_path.is_file(), f"closed-class list references a non-existent file: {relpath}"
    document = _load_ordered(schema_path)
    assert document.get("additionalProperties") is False, (
        f"{relpath}: compat_class closed contract must declare "
        f"'additionalProperties: false' at the schema root"
    )


def test_enum_closed_contract_seals_via_enum_not_additional_properties() -> None:
    """common/engine-id/v1: closed via its `enum` array (root type:string),
    not additionalProperties (inapplicable to a non-object schema).
    """
    for relpath in ENUM_CLOSED_SCHEMA_RELPATHS:
        schema_path = JSON_SCHEMA_DIR / relpath
        document = _load_ordered(schema_path)
        assert document.get("type") == "string", f"{relpath}: expected root type:string"
        assert isinstance(document.get("enum"), list) and document["enum"], (
            f"{relpath}: expected a non-empty root 'enum' array as the closing mechanism"
        )
        assert "additionalProperties" not in document, (
            f"{relpath}: additionalProperties is inapplicable to a string-rooted schema; "
            "if this schema gained a root object type it must move into "
            "CLOSED_CLASS_SCHEMA_RELPATHS with additionalProperties:false instead"
        )


def test_defs_only_closed_contract_has_no_root_type_to_seal() -> None:
    """common/identifiers/v1 is closed but $defs-only -- documents/locks
    the exclusion rationale rather than silently skipping it.
    """
    for relpath in DEFS_ONLY_CLOSED_SCHEMA_RELPATHS:
        schema_path = JSON_SCHEMA_DIR / relpath
        document = _load_ordered(schema_path)
        assert "type" not in document, (
            f"{relpath}: expected no root 'type' (defs-only reuse surface); if this schema "
            "gained a root type it needs additionalProperties:false and must move into "
            "CLOSED_CLASS_SCHEMA_RELPATHS, not stay in this exclusion set"
        )
        assert "$defs" in document


def test_frozen_envelope_seals_via_uneval_properties_on_each_oneof_branch() -> None:
    for relpath in FROZEN_ONE_OF_UNEVALUATED_RELPATHS:
        schema_path = JSON_SCHEMA_DIR / relpath
        document = _load_ordered(schema_path)
        assert "oneOf" in document, f"{relpath}: expected root oneOf (3 context_type branches)"
        defs = document.get("$defs", {})
        branch_names = [ref["$ref"].split("/")[-1] for ref in document["oneOf"] if "$ref" in ref]
        assert branch_names, f"{relpath}: oneOf branches must be $ref'd $defs entries"
        for branch_name in branch_names:
            branch = defs.get(branch_name)
            assert branch is not None, f"{relpath}: oneOf $ref {branch_name!r} missing from $defs"
            assert branch.get("unevaluatedProperties") is False, (
                f"{relpath}: $defs.{branch_name} must seal via 'unevaluatedProperties: false' "
                "(frozen envelope's per-branch closing mechanism, distinct from root "
                "additionalProperties:false used by every other closed contract)"
            )


# --------------------------------------------------------------------------
# Cross-file $ref conventions: relative, /vN/-pinned, common-category-only,
# no absolute https:// $ref.
# --------------------------------------------------------------------------


def _iter_refs(node: Any) -> list[str]:
    """Recursively collect every '$ref' string value in a parsed schema doc."""
    refs: list[str] = []
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            refs.append(ref)
        for value in node.values():
            refs.extend(_iter_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_iter_refs(item))
    return refs


def _cross_file_refs(refs: list[str]) -> list[str]:
    """Filter to only cross-file refs -- i.e. not a bare '#/...' internal
    pointer and not a same-document root ref ('#').
    """
    return [r for r in refs if not r.startswith("#")]


@pytest.mark.parametrize("schema_path", ALL_SCHEMA_FILES, ids=_relpath)
def test_no_absolute_https_ref(schema_path: Path) -> None:
    document = _load_ordered(schema_path)
    refs = _iter_refs(document)
    for ref in refs:
        assert not ref.startswith("https://"), (
            f"{_relpath(schema_path)}: $ref {ref!r} is an absolute https:// URI -- "
            "cross-file $refs in this catalog must be relative (ADR-0011/ruling R3, "
            "check-jsonschema CLI would try to fetch it over the network)"
        )


@pytest.mark.parametrize("schema_path", ALL_SCHEMA_FILES, ids=_relpath)
def test_cross_file_refs_relative_and_version_pinned_and_common_only(schema_path: Path) -> None:
    document = _load_ordered(schema_path)
    refs = _iter_refs(document)
    cross_file = _cross_file_refs(refs)
    relpath = _relpath(schema_path)
    for ref in cross_file:
        assert ref.startswith("../"), (
            f"{relpath}: cross-file $ref {ref!r} must be a relative '../' path"
        )
        assert _RELATIVE_REF_WITH_VERSION_PATTERN.match(ref), (
            f"{relpath}: cross-file $ref {ref!r} must be /vN/-pinned (shape check)"
        )
        # Resolve the ref (path portion only, strip any '#...' fragment)
        # against schema_path's own directory and assert the resolved
        # file actually lives under json-schema/common/ -- the shape
        # regex alone cannot distinguish "up-then-into-common" from
        # "up-then-into-some-other-category" for every possible relative
        # depth, so resolve for real.
        ref_path_part = ref.split("#", 1)[0]
        resolved = (schema_path.parent / ref_path_part).resolve()
        try:
            resolved_relpath = resolved.relative_to(JSON_SCHEMA_DIR)
        except ValueError:
            pytest.fail(f"{relpath}: cross-file $ref {ref!r} resolves outside {JSON_SCHEMA_DIR}")
        assert resolved_relpath.parts[0] == "common", (
            f"{relpath}: cross-file $ref {ref!r} resolves to {resolved_relpath} -- "
            "cross-file $refs in this catalog must target the common/ category only"
        )
        assert resolved.is_file(), (
            f"{relpath}: cross-file $ref {ref!r} resolves to a non-existent file {resolved}"
        )


def test_at_least_one_schema_uses_a_cross_file_common_ref() -> None:
    """Meta-test: proves the cross-file $ref lint is actually exercised on
    real data (e.g. tenant-context.schema.json -> common/identifiers,
    common/engine-id), not vacuously passing because no schema in the
    catalog happens to use a cross-file $ref.
    """
    found = False
    for schema_path in ALL_SCHEMA_FILES:
        document = _load_ordered(schema_path)
        if _cross_file_refs(_iter_refs(document)):
            found = True
            break
    assert found, "expected at least one schema file with a cross-file $ref"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
