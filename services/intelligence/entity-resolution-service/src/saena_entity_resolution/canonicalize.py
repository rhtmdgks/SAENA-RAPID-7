"""Alias -> canonical `EntityRecord` resolution (w4-03).

Core domain logic: given a tenant/project-scoped set of `AliasGroup`
requests (one canonical entity per group, each carrying every alias string
that should resolve to it), produce one `EntityRecord` domain object per
group — using the generated model `saena_schemas.domain.entity_record_v1.
EntityRecord` directly (no duplicate DTO, ADR-0011 codegen-is-SSOT
discipline) — plus a deterministic `graph_version` hash for the whole
resolved set.

**Ownership rule (fail-closed, w4-03 mission)**: a `competitor` entity is
NEVER marked as owned/first-party. `AliasGroup.is_owned=True` combined with
`entity_type="competitor"` raises `CompetitorOwnershipDeniedError` before any
`EntityRecord` is constructed — this is checked unconditionally, not an
opt-out flag, matching this repo's precedent of fail-closed gates that
cannot be silently bypassed (see CLAUDE.md operating principle 3, and the
w3-14 "no F-5 opt-out" precedent in the recent commit history this session's
memory cites).

**Determinism (w4-03 mission)**: `graph_version` is computed via
`saena_domain.audit.canonical.canonical_json` + `sha256_hex` — the SAME
canonicalization the audit hash-chain (`saena_domain.audit.chain`/
`hashing`) and the w4-09 experiment ledger (`saena_domain.experiment.
ledger.compute_experiment_hash`) both reuse verbatim. No new hashing rule is
invented here. Identical input (same tenant_id/project_id/resolved entity
set, ignoring `updated_at` — see `_hashable_fields`) always produces a
byte-identical `graph_version` string, regardless of process/machine/input
ordering (alias-group order and within-group alias order are both
normalized away before hashing).

`updated_at` is deliberately EXCLUDED from the hashed material: two
resolution runs over byte-identical alias input at two different wall-clock
instants must still produce the same `graph_version` (that is the whole
point of "identical input -> byte-identical graph_version hash" — a
timestamp is not part of the graph's logical content). Callers that need
freshness tracking read `EntityRecord.updated_at` directly; it never
participates in the version hash.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from saena_domain.audit.canonical import canonical_json, sha256_hex
from saena_schemas.domain.entity_record_v1 import EntityRecord
from saena_schemas.domain.entity_record_v1 import EntityType as _SchemaEntityType

from saena_entity_resolution.errors import (
    AliasConflictError,
    CompetitorOwnershipDeniedError,
    EmptyAliasSetError,
)

#: Re-exported so callers never need to import the generated schema module
#: directly just to reference an entity-type value (mirrors
#: `saena_domain.identity.tenant` wrapping generated enums/models rather
#: than re-defining them).
EntityType = _SchemaEntityType

_SHA256_PREFIX = "sha256:"


def _utc_now_iso() -> str:
    """Render the current UTC instant in the `TimestampUtc` contract shape
    (`^[0-9]{4}-...Z$`) — matches `saena_site_discovery.inventory._utc_now_iso`."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class AliasGroup:
    """One canonicalization request: every alias string that should resolve
    to a single canonical entity, plus the entity's identity/type/ownership.

    `aliases` may be empty at the type level but `resolve_entities` rejects
    an empty group (`EmptyAliasSetError`) — there is nothing to canonicalize
    if no alias strings are supplied. `canonical_name` is the entity's
    resolved display name (independent of how many alias strings map to it);
    it does not itself have to appear in `aliases`.
    """

    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: tuple[str, ...]
    is_owned: bool = False


@dataclass(frozen=True, slots=True)
class EntityResolutionResult:
    """`resolve_entities`'s return value: the resolved `EntityRecord` tuple
    (stable order: input `AliasGroup` order) plus the deterministic
    `graph_version` hash computed over that same resolved set."""

    tenant_id: str
    project_id: str
    entities: tuple[EntityRecord, ...]
    graph_version: str


def _normalize_aliases(aliases: Iterable[str]) -> tuple[str, ...]:
    """Case-folded, deduplicated, sorted alias set (order-independent input
    always normalizes to the same tuple — required for deterministic
    hashing)."""
    seen: dict[str, None] = {}
    for alias in aliases:
        key = alias.strip().casefold()
        if key:
            seen[key] = None
    return tuple(sorted(seen))


def _check_ownership_rule(group: AliasGroup) -> None:
    """Fail-closed: `entity_type == competitor` may never carry
    `is_owned=True`. Unconditional — no bypass flag exists anywhere in this
    module's public surface."""
    if group.entity_type == EntityType.competitor and group.is_owned:
        raise CompetitorOwnershipDeniedError(
            f"entity_id {group.entity_id!r} is entity_type='competitor' and "
            "cannot be marked is_owned=True — a competitor entity is never "
            "attributed first-party ownership",
            context={"entity_id": group.entity_id, "entity_type": group.entity_type.value},
        )


def _check_no_cross_group_alias_conflict(groups: Sequence[AliasGroup]) -> None:
    """Fail closed if the SAME normalized alias string appears in two
    different `AliasGroup`s within one resolution request — that alias
    cannot unambiguously resolve to a single canonical entity."""
    owner_of: dict[str, str] = {}
    for group in groups:
        for alias in _normalize_aliases(group.aliases):
            existing_entity_id = owner_of.get(alias)
            if existing_entity_id is not None and existing_entity_id != group.entity_id:
                raise AliasConflictError(
                    f"alias {alias!r} maps to both entity_id "
                    f"{existing_entity_id!r} and {group.entity_id!r} within the "
                    "same resolution request",
                    context={
                        "alias": alias,
                        "entity_id_a": existing_entity_id,
                        "entity_id_b": group.entity_id,
                    },
                )
            owner_of[alias] = group.entity_id


def _check_no_duplicate_entity_id(groups: Sequence[AliasGroup]) -> None:
    """Fail closed if two `AliasGroup`s in the same request declare the same
    `entity_id` with a different `canonical_name`/`entity_type`/`is_owned` —
    ambiguous canonicalization target."""
    seen: dict[str, AliasGroup] = {}
    for group in groups:
        existing = seen.get(group.entity_id)
        if existing is not None and (
            existing.canonical_name != group.canonical_name
            or existing.entity_type != group.entity_type
            or existing.is_owned != group.is_owned
        ):
            raise AliasConflictError(
                f"entity_id {group.entity_id!r} is declared twice with "
                "conflicting canonical_name/entity_type/is_owned in the same "
                "resolution request",
                context={"entity_id": group.entity_id},
            )
        seen[group.entity_id] = group


def _hashable_group_fields(group: AliasGroup) -> dict[str, Any]:
    """The subset of `AliasGroup` content that determines an `EntityRecord`'s
    identity — everything the eventual record carries EXCEPT `graph_version`
    (circular: the field being computed) and `updated_at` (see module
    docstring "Determinism" — never participates in the version hash)."""
    return {
        "entity_id": group.entity_id,
        "entity_type": group.entity_type.value,
        "canonical_name": group.canonical_name,
    }


def compute_graph_version(
    tenant_id: str, project_id: str, alias_groups: Sequence[AliasGroup]
) -> str:
    """Deterministic content hash of the resolved `(tenant_id, project_id,
    alias_groups)` graph — see module docstring "Determinism". Groups are
    sorted by `entity_id` before hashing so caller-supplied `AliasGroup`
    order never affects the resulting hash. Hashes the RESOLVED identity
    fields only (`entity_id`/`entity_type`/`canonical_name`) — never
    `graph_version` itself (that would be circular) or `updated_at` (a
    timestamp, not graph content).
    """
    material = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "entities": [
            _hashable_group_fields(group)
            for group in sorted(alias_groups, key=lambda group: group.entity_id)
        ],
    }
    digest = sha256_hex(canonical_json(material))
    return f"{_SHA256_PREFIX}{digest}"


def resolve_entities(
    *,
    tenant_id: str,
    project_id: str,
    alias_groups: Sequence[AliasGroup],
    clock: Callable[[], str] = _utc_now_iso,
) -> EntityResolutionResult:
    """Canonicalize every `AliasGroup` in `alias_groups` into one
    `EntityRecord` each, and compute the resolved graph's deterministic
    `graph_version` hash.

    Validation order (fail-closed, first violation wins):
      1. Every group has >=1 non-empty alias (`EmptyAliasSetError`).
      2. No `entity_id` is declared twice with conflicting attributes
         (`AliasConflictError`).
      3. No normalized alias string is claimed by two different entities
         (`AliasConflictError`).
      4. No `competitor` entity is marked `is_owned=True`
         (`CompetitorOwnershipDeniedError`) — checked per-group, so this is
         also caught even for a single-group request.

    `clock` is injectable (defaults to real UTC now) purely for
    `EntityRecord.updated_at` — since that field is excluded from the
    `graph_version` hash (see module docstring), injecting a fixed clock is
    a convenience for deterministic *record* fixtures in tests, not a
    requirement for `graph_version` determinism itself (that already holds
    with the real clock, since `updated_at` never enters the hash).
    """
    for group in alias_groups:
        if not _normalize_aliases(group.aliases):
            raise EmptyAliasSetError(
                f"entity_id {group.entity_id!r} has no non-empty aliases to canonicalize",
                context={"entity_id": group.entity_id},
            )

    _check_no_duplicate_entity_id(alias_groups)
    _check_no_cross_group_alias_conflict(alias_groups)

    for group in alias_groups:
        _check_ownership_rule(group)

    # Computed from `alias_groups` directly (not from already-built
    # `EntityRecord`s) — `graph_version` must be known before any record can
    # be constructed, since it is itself one of `EntityRecord`'s required,
    # non-empty fields (constructing a placeholder-then-patch instance would
    # transiently violate that contract).
    graph_version = compute_graph_version(tenant_id, project_id, alias_groups)

    # `model_validate(dict)` rather than the keyword constructor (matches
    # `saena_domain.identity.tenant.TenantContext.from_payload`'s
    # established precedent for generated pydantic models whose fields are
    # RootModel-wrapped value objects (`TenantId`/`ProjectId`/
    # `TimestampUtc`) — passing plain `str` lets pydantic's own runtime
    # coercion/validation populate those wrapper types, and keeps this
    # module mypy-clean without a duplicate hand-written wrapper-construction
    # step the generated model already performs internally.
    observed_at = clock()
    entities = tuple(
        EntityRecord.model_validate(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "entity_id": group.entity_id,
                "graph_version": graph_version,
                "entity_type": group.entity_type,
                "canonical_name": group.canonical_name,
                "updated_at": observed_at,
            }
        )
        for group in alias_groups
    )

    return EntityResolutionResult(
        tenant_id=tenant_id,
        project_id=project_id,
        entities=entities,
        graph_version=graph_version,
    )


__all__ = [
    "AliasGroup",
    "EntityResolutionResult",
    "EntityType",
    "compute_graph_version",
    "resolve_entities",
]
