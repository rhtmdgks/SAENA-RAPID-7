"""Structural JSON Schema diff for contract compatibility checks (ADR-0012).

`structural_diff()` is MOVED verbatim (per plan §2 "MOVE structural_diff to
harness.diff, not copy") from the W0 bootstrap implementation in
`tests/contract/test_compat_selfdiff.py`, then extended for W1 real-tag
wiring:

  (a) items recursion       -- array `items` schema is now walked, not
                                just `properties`/`$defs`/combiners.
  (b) within-file $ref       -- `#/$defs/...` refs are resolved (with a
      resolution                visited-set cycle guard) before comparison
                                at each node, so ref-indirected changes are
                                still detected structurally.
  (c) const change            -- treated like an enum change (both
                                directions breaking, same rationale as
                                ADR-0012's enum ruling: a const change is
                                degenerate single-value enum narrowing +
                                widening simultaneously).
  (d) cross-file $ref compare -- a shallow, string-level comparison: if a
                                node's `$ref` is an external (non
                                "#/...") URI and that URI string changed
                                between before/after, flag
                                "external-ref-changed". This is
                                deliberately shallow (string compare, not
                                bundle resolution) -- ruling R3 assigns
                                full cross-file bundle comparison to each
                                referenced document's own compat check,
                                not to the referencing document's diff;
                                bundle-level comparison is registered as a
                                W2 improvement item, not silently dropped.
  (e) pattern change          -- a `pattern` added, removed, or changed on
                                the same node is breaking in both
                                directions (ruling R5, to be recorded in
                                ADR-0024: pattern change is promoted from
                                warn-only to breaking, structurally
                                identical to the enum both-directions
                                rule).

The function stays pure / data-in-data-out: `structural_diff(before, after)
-> list[str]`, no I/O, no registry/tag knowledge. Callers (`harness.rules`,
`tests/contract/compat/*`) supply already-loaded schema dicts.
"""

from __future__ import annotations

from typing import Any

_REF_KEY = "$ref"


def structural_diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Recursively compare two JSON Schema documents (or subschemas) and
    return a list of human-readable breaking-change descriptions.

    Detects (per ADR-0012 event-payload rules, applied conservatively):
      - required-add:   a property added to `required` that was not
                         required before (new mandatory field breaks old
                         producers/consumers that omit it).
      - required-remove: a property removed from `required` -- treated as
                          breaking here because dropping a guarantee a
                          consumer already relies on is not detectable as
                          safe without consumer-side knowledge; the single
                          harness (ADR-0012) flags it for human review.
      - type-narrow:    a property's `type` changed such that the new
                         type set is a strict subset of the old one
                         (fewer accepted JSON types than before).
      - enum-change:    an `enum` list gained or lost any value (ADR-0012:
                         both narrowing and widening are breaking).
      - const-change:   a `const` value added, removed, or changed (W1
                         extension (c) -- treated like enum-change).
      - pattern-changed: a `pattern` value added, removed, or changed on
                         the same node (W1 extension (e), ruling R5 --
                         both directions breaking).
      - external-ref-changed: a node's `$ref` is an external
                         (non-"#/...") URI whose string value changed
                         between before/after (W1 extension (d), shallow
                         cross-file comparison, ruling R3).

    Does NOT flag (non-breaking, per ADR-0012 "optional field addition
    = minor"):
      - a new optional property (present in `properties` but absent from
        `required` in both before/after, or newly added to `properties`
        without also being added to `required`).
      - type widening (new type superset of old type set) -- permissive,
        flagged nowhere in ADR-0012 as breaking; left non-breaking here.

    Walks `properties`, `items`, `required`, `enum`, `const`, `pattern`,
    `$ref`, `$defs`, and `oneOf`/`anyOf`/`allOf` branches recursively.
    Within-file `#/$defs/...` refs are resolved before comparison at each
    node (cycle-guarded); external refs are compared shallowly as strings
    rather than resolved (ruling R3 -- bundle-level cross-file comparison
    is W2 scope).
    """
    violations: list[str] = []
    _diff_node(
        before,
        after,
        path="$",
        violations=violations,
        before_root=before,
        after_root=after,
        before_visited=frozenset(),
        after_visited=frozenset(),
    )
    return violations


def _as_type_set(type_value: Any) -> set[str]:
    if type_value is None:
        return set()
    if isinstance(type_value, str):
        return {type_value}
    if isinstance(type_value, list):
        return set(type_value)
    return set()


def _is_internal_ref(ref: str) -> bool:
    return ref.startswith("#/")


def _resolve_internal_ref(root: dict[str, Any], ref: str) -> dict[str, Any] | None:
    """Resolve a "#/a/b/c" JSON Pointer ref against `root`. Returns None if
    unresolvable (missing path or non-dict target) rather than raising --
    an unresolvable internal ref is a schema-authoring problem caught
    elsewhere (metaschema/validate suite), not this diff function's job.
    """
    if not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/") if ref != "#/" else []
    node: Any = root
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node if isinstance(node, dict) else None


def _resolve_node(
    node: dict[str, Any],
    root: dict[str, Any],
    visited: frozenset[str],
) -> tuple[dict[str, Any], frozenset[str]]:
    """If `node` is a `{"$ref": "#/..."}` internal ref, resolve it
    (cycle-guarded via `visited`). Returns (resolved_node, updated_visited).
    External refs and non-ref nodes are returned unchanged.
    """
    ref = node.get(_REF_KEY)
    if not isinstance(ref, str) or not _is_internal_ref(ref):
        return node, visited
    if ref in visited:
        # Cycle guard: stop resolving further, compare the ref node itself
        # (still surfaces external-ref/pattern/etc. changes on this node,
        # just does not recurse infinitely into a self-referential $defs
        # cycle).
        return node, visited
    resolved = _resolve_internal_ref(root, ref)
    if resolved is None:
        return node, visited
    return resolved, visited | {ref}


def _diff_node(
    before: dict[str, Any] | Any,
    after: dict[str, Any] | Any,
    path: str,
    violations: list[str],
    before_root: dict[str, Any],
    after_root: dict[str, Any],
    before_visited: frozenset[str],
    after_visited: frozenset[str],
) -> None:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return

    # (d) external $ref string comparison -- BEFORE internal-ref resolution,
    # since resolution only applies to internal ("#/...") refs; an external
    # ref is compared as-is and then, since it cannot be resolved locally,
    # diffing stops descending through it (nothing more to structurally
    # compare without fetching the external document -- ruling R3, W2).
    before_ref = before.get(_REF_KEY)
    after_ref = after.get(_REF_KEY)
    before_ref_external = isinstance(before_ref, str) and not _is_internal_ref(before_ref)
    after_ref_external = isinstance(after_ref, str) and not _is_internal_ref(after_ref)
    if before_ref_external or after_ref_external:
        if before_ref != after_ref:
            violations.append(
                f"{path}: external-ref-changed before={before_ref!r} after={after_ref!r}"
            )
        # Do not descend further into an externally-$ref'd node.
        return

    # (b) within-file $ref resolution (visited-set cycle guard) before
    # comparison at this node.
    before, before_visited = _resolve_node(before, before_root, before_visited)
    after, after_visited = _resolve_node(after, after_root, after_visited)
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

    # enum-change (narrow or widen -- both breaking per ADR-0012)
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

    # (c) const-change -- treated like an enum change (both directions
    # breaking; a const value change is a degenerate simultaneous
    # narrow+widen of a single-value enum).
    _CONST_ABSENT = object()
    before_const = before.get("const", _CONST_ABSENT)
    after_const = after.get("const", _CONST_ABSENT)
    const_present = before_const is not _CONST_ABSENT or after_const is not _CONST_ABSENT
    if const_present and before_const != after_const:
        violations.append(f"{path}: const-change before={before_const!r} after={after_const!r}")

    # (e) pattern-changed -- added, removed, or changed, both directions
    # breaking (ruling R5).
    _PATTERN_ABSENT = object()
    before_pattern = before.get("pattern", _PATTERN_ABSENT)
    after_pattern = after.get("pattern", _PATTERN_ABSENT)
    pattern_present = before_pattern is not _PATTERN_ABSENT or after_pattern is not _PATTERN_ABSENT
    if pattern_present and before_pattern != after_pattern:
        violations.append(
            f"{path}: pattern-changed before={before_pattern!r} after={after_pattern!r}"
        )

    # Recurse into properties (shared keys only -- new/removed *properties*
    # without a required-add/remove are non-breaking additions/removals
    # of optional fields and are intentionally not flagged here).
    before_props = before.get("properties", {})
    after_props = after.get("properties", {})
    if isinstance(before_props, dict) and isinstance(after_props, dict):
        for key in sorted(set(before_props) & set(after_props)):
            _diff_node(
                before_props[key],
                after_props[key],
                f"{path}.properties.{key}",
                violations,
                before_root,
                after_root,
                before_visited,
                after_visited,
            )

    # (a) Recurse into `items` (array items schema). Only handles the
    # single-schema form (`items: {...}`) -- 2020-12's tuple form uses
    # `prefixItems`, out of scope until a contract needs it (registered,
    # not silently dropped: no contract in the P0 12 catalog uses tuple
    # validation per the plan's field-source table).
    before_items = before.get("items")
    after_items = after.get("items")
    if isinstance(before_items, dict) and isinstance(after_items, dict):
        _diff_node(
            before_items,
            after_items,
            f"{path}.items",
            violations,
            before_root,
            after_root,
            before_visited,
            after_visited,
        )

    # Recurse into $defs
    before_defs = before.get("$defs", {})
    after_defs = after.get("$defs", {})
    if isinstance(before_defs, dict) and isinstance(after_defs, dict):
        for key in sorted(set(before_defs) & set(after_defs)):
            _diff_node(
                before_defs[key],
                after_defs[key],
                f"{path}.$defs.{key}",
                violations,
                before_root,
                after_root,
                before_visited,
                after_visited,
            )

    # Recurse into oneOf/anyOf/allOf branches positionally.
    for combiner in ("oneOf", "anyOf", "allOf"):
        before_branches = before.get(combiner)
        after_branches = after.get(combiner)
        if isinstance(before_branches, list) and isinstance(after_branches, list):
            for idx, (b_branch, a_branch) in enumerate(
                zip(before_branches, after_branches, strict=False)
            ):
                _diff_node(
                    b_branch,
                    a_branch,
                    f"{path}.{combiner}[{idx}]",
                    violations,
                    before_root,
                    after_root,
                    before_visited,
                    after_visited,
                )
