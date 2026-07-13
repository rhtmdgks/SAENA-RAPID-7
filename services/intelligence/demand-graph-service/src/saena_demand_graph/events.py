"""`demand.graph.versioned.v1` event payload + envelope construction.

**Isolated forward-dependency gap (documented per task instruction "If you
hit a genuinely OPEN decision... isolate it behind a port/synthetic and
document it")**: `docs/architecture/wave4-plan.md`'s Stage-1 DAG lists
`demand.graph.versioned.v1` under "NEW (Contracts Steward, w4-10)" —
i.e. the generated pydantic payload model
`saena_schemas.event.demand_graph_versioned_v1` and the AsyncAPI catalog
channel entry this event needs do NOT exist yet in this worktree (verified:
`packages/schemas/saena_schemas/event/` has no `demand_graph_versioned_v1`
member as of this patch unit; w4-02 and w4-10 are parallel Stage-1 siblings
with no path overlap — w4-02 never touches `packages/contracts`/
`packages/schemas`, CLAUDE.md §7 single-owner). Calling the real
`saena_domain.events.factory.EnvelopeFactory.build_tenant_envelope` with
`event_type="demand.graph.versioned.v1"` today would raise
`TopicMismatchError` (unknown AsyncAPI channel) — this is a real, external,
not-yet-landed dependency, not a design choice available to this unit.

Per `services/foundation/tenant-control-service/src/saena_tenant_control/
service.py`'s established precedent ("Why no `tenant.policy.updated.v1`
event" docstring) for the identical situation: never bypass
`EnvelopeFactory`'s catalog check, and never hand-build a raw dict that
merely *looks* like a valid envelope. This module instead:

1. `build_demand_graph_versioned_payload` — builds and validates the exact
   4-field payload dict the mission specifies
   (`{project_id, graph_version, cluster_count, provenance_ref}`), with NO
   dependency on the not-yet-generated schema.
2. `EventEnvelopeBuilderPort` — a structural `Protocol` matching
   `EnvelopeFactory.build_tenant_envelope`'s exact keyword signature. The
   REAL `EnvelopeFactory.build_tenant_envelope` already satisfies this
   Protocol as-is (nothing about it is faked/reimplemented) — once w4-10
   registers the `demand.graph.versioned.v1` channel + generated model,
   production wiring is passing `EnvelopeFactory.build_tenant_envelope`
   itself as `envelope_builder` with ZERO changes to this module.
3. `emit_demand_graph_versioned_event` — calls the injected
   `envelope_builder` port with the built payload. This module's own unit
   tests inject a deterministic fake port (proves this module's own
   plumbing — field mapping, tenant/run threading, idempotency-key shape —
   is correct) and separately prove (`test_events.py`) that the payload
   ALONE (independent of any envelope) is well-formed per the mission's
   exact field list, so both this module's logic and its forward-compatible
   shape are covered without asserting a not-yet-approved topic into the
   production AsyncAPI catalog from this unit's exclusive write paths.
"""

from __future__ import annotations

from typing import Any, Protocol

from saena_demand_graph.errors import MaterialValidationError
from saena_demand_graph.records import DemandGraph

#: The exact `demand.graph.versioned.v1` event_type string this package
#: will publish under once w4-10 registers the topic — kept as a single
#: named constant so both `emit_demand_graph_versioned_event` and every test
#: reference the same literal.
DEMAND_GRAPH_VERSIONED_EVENT_TYPE = "demand.graph.versioned.v1"

#: This service's producer identity (matches `README.md`'s service name —
#: mirrors how `saena_tenant_control`/`saena_plan_contract` name their own
#: `producer` string as their own service slug).
DEMAND_GRAPH_PRODUCER = "demand-graph-service"


def build_demand_graph_versioned_payload(graph: DemandGraph) -> dict[str, Any]:
    """Build the `demand.graph.versioned.v1` payload dict for `graph`.

    Exactly the 4 fields the mission specifies:
    `{project_id, graph_version, cluster_count, provenance_ref}` — no
    `tenant_id`/`run_id` (ADR-0024(e) payload must not re-project envelope-
    level identifiers, mirrored here even before this reaches a real
    `EnvelopeFactory` call) and no raw cluster content (mission: "NO PII,
    secrets, or raw customer source in event payloads" — clusters themselves
    are never serialized into the event, only the graph's own version hash/
    count/provenance).
    """
    if not graph.clusters:
        # Defense-in-depth: `builder.build_demand_graph` already refuses an
        # empty material set (which would make this unreachable in
        # practice), but a payload builder must never silently emit a
        # `cluster_count: 0` "success" event for a hand-constructed
        # `DemandGraph` a caller assembled some other way.
        raise MaterialValidationError(
            "cannot build a demand.graph.versioned.v1 payload for a graph with zero clusters",
            context={"tenant_id": graph.tenant_id, "project_id": graph.project_id},
        )
    return {
        "project_id": graph.project_id,
        "graph_version": graph.graph_version,
        "cluster_count": len(graph.clusters),
        "provenance_ref": graph.provenance_ref,
    }


class EventEnvelopeBuilderPort(Protocol):
    """Structural match of `saena_domain.events.factory.EnvelopeFactory.
    build_tenant_envelope`'s keyword signature — see module docstring.
    The real `EnvelopeFactory.build_tenant_envelope` satisfies this
    Protocol unmodified."""

    def __call__(
        self,
        *,
        producer: str,
        event_type: str,
        tenant_id: str,
        run_id: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


def _idempotency_key(*, tenant_id: str, run_id: str, project_id: str, graph_version: str) -> str:
    """`f"{tenant_id}:{run_id}:{project_id}:{graph_version}"` — mirrors the
    `patch.unit.completed.v1` idempotency-key composition convention
    documented in `saena_domain.events.factory.EnvelopeFactory`'s own
    docstring (`f"{tenant_id}:{run_id}:{patch_unit_id}"`), extended with
    `graph_version` so a re-run over identical input (same tenant/run/
    project/graph_version) is recognized as the SAME event rather than
    double-published — appropriate for a canonical-deterministic artifact
    where the version hash IS the content identity.
    """
    return f"{tenant_id}:{run_id}:{project_id}:{graph_version}"


def emit_demand_graph_versioned_event(
    *,
    graph: DemandGraph,
    run_id: str,
    envelope_builder: EventEnvelopeBuilderPort,
) -> dict[str, Any]:
    """Build the `demand.graph.versioned.v1` payload for `graph` and pass it
    through `envelope_builder` (see `EventEnvelopeBuilderPort`) to produce a
    full tenant-context event envelope. Returns the envelope dict
    `envelope_builder` returns, unmodified.
    """
    payload = build_demand_graph_versioned_payload(graph)
    return envelope_builder(
        producer=DEMAND_GRAPH_PRODUCER,
        event_type=DEMAND_GRAPH_VERSIONED_EVENT_TYPE,
        tenant_id=graph.tenant_id,
        run_id=run_id,
        idempotency_key=_idempotency_key(
            tenant_id=graph.tenant_id,
            run_id=run_id,
            project_id=graph.project_id,
            graph_version=graph.graph_version,
        ),
        payload=payload,
    )


__all__ = [
    "DEMAND_GRAPH_PRODUCER",
    "DEMAND_GRAPH_VERSIONED_EVENT_TYPE",
    "EventEnvelopeBuilderPort",
    "build_demand_graph_versioned_payload",
    "emit_demand_graph_versioned_event",
]
