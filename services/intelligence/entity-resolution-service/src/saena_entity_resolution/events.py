"""`entity.graph.versioned.v1` payload + envelope builders (w4-03).

Mirrors `saena_domain.execution.events.build_site_inventory_completed_payload`'s
shape exactly (build payload dict -> validate against the generated pydantic
payload model -> return the validated dict) — no duplicate DTO, ADR-0011
codegen-is-SSOT discipline. This module lives inside
`saena_entity_resolution` (not `saena_domain.execution`) because
`packages/domain/**` is outside this patch unit's exclusive write paths;
functionally it is the same "payload builder" pattern that module already
establishes for the 4 Wave 3 job-kind events.

`producer="entity-resolution-service"` is fixed (not a caller parameter) —
`saena_domain.events._topics.load_topic_catalog()`'s
`entity.graph.versioned.v1` `TopicInfo.expected_producer` is exactly that
string (see `packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml`
`operations.sendEntityGraphVersioned.summary`); any other producer value
would be rejected by `EnvelopeFactory`'s own `ProducerMismatchError` check,
so hardcoding it here removes a whole class of caller mistake rather than
just documenting the constraint.

This channel does NOT require `payload.engine_id`
(`x-saena-engine-id-required` is absent from `entity.graph.versioned.v1` in
the AsyncAPI catalog) — entity-graph versioning is a project-scoped
canonicalization notification, not a per-engine observation/citation/
experiment-outcome event, so no `engine_id` field or ChatGPT-Search guard
applies here (CLAUDE.md engine scope still constrains the 3 engine_id-
required channels; this one is outside that set by design).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from saena_domain.events.factory import EnvelopeFactory
from saena_schemas.event.entity_graph_versioned_v1 import EntityGraphVersionedV1Payload

from saena_entity_resolution.errors import EntityResolutionError
from saena_entity_resolution.graph import EntityGraph

_PRODUCER = "entity-resolution-service"
_EVENT_TYPE = "entity.graph.versioned.v1"


class EntityGraphEventValidationError(EntityResolutionError):
    """The built `entity.graph.versioned.v1` payload does not conform to
    `EntityGraphVersionedV1Payload` (should be unreachable in normal use —
    `build_entity_graph_versioned_payload` derives every field from an
    already-valid `EntityGraph`; this guards against a future field-shape
    drift between this module and the generated contract)."""

    error_code = "saena.validation.entity_graph_event_payload_invalid"


def build_entity_graph_versioned_payload(graph: EntityGraph) -> dict[str, Any]:
    """`entity.graph.versioned.v1` payload for `graph`: exactly
    `{project_id, graph_version, entity_count, provenance_ref}` (w4-03
    mission spec), validated against the generated
    `EntityGraphVersionedV1Payload` model before being returned.
    """
    payload = {
        "project_id": graph.project_id,
        "graph_version": graph.graph_version,
        "entity_count": graph.entity_count,
        "provenance_ref": graph.provenance_ref,
    }
    try:
        instance = EntityGraphVersionedV1Payload.model_validate(payload)
    except ValidationError as exc:
        raise EntityGraphEventValidationError(
            f"built entity.graph.versioned.v1 payload does not conform to its "
            f"payload contract: {exc}",
            context={"project_id": graph.project_id},
        ) from exc
    return instance.model_dump(mode="json")


def build_entity_graph_versioned_envelope(
    graph: EntityGraph,
    *,
    run_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Full tenant-context envelope for `entity.graph.versioned.v1`, built
    via `saena_domain.events.factory.EnvelopeFactory.build_tenant_envelope`
    (dual jsonschema+pydantic validated there) wrapping
    `build_entity_graph_versioned_payload(graph)`.

    `idempotency_key` is always caller-supplied (matches
    `EnvelopeFactory`'s own "caller owns per-event key composition" contract
    — see that class's docstring); a natural choice for this event is
    `f"{tenant_id}:{project_id}:{graph_version}"` (mirrors the
    `EntityRecord` idempotency key `entity_id+graph_version` the contract's
    own `$comment` documents, generalized to the whole-graph event), but this
    function does not impose that shape.
    """
    payload = build_entity_graph_versioned_payload(graph)
    return EnvelopeFactory.build_tenant_envelope(
        producer=_PRODUCER,
        event_type=_EVENT_TYPE,
        tenant_id=graph.tenant_id,
        run_id=run_id,
        idempotency_key=idempotency_key,
        payload=payload,
    )


__all__ = [
    "EntityGraphEventValidationError",
    "build_entity_graph_versioned_envelope",
    "build_entity_graph_versioned_payload",
]
