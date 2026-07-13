"""saena_demand_graph — demand-graph-service (W4, unit w4-02).

Deterministic, offline, first-party-only B2B-SaaS query-cluster (demand
graph) builder. Input: approved `records.FirstPartyMaterial` items only (no
external/scraped demand data, no network, no wall-clock/random
nondeterminism). Output: `records.DemandGraph` — canonical, deterministic
(`graph_version`/`provenance_ref` are both content-addressed `sha256:`
digests over the actual build input; identical input always yields
byte-identical output), tenant-scoped, with a `demand.graph.versioned.v1`
event payload builder (`events.py`).

W4 MINIMAL scope — explicitly OUT of this package (later Wave-4 units or
Wave 5, deliberately not implemented here): a real persistence adapter
(`store.InMemoryDemandGraphStore` is a reference in-memory store only), the
real `demand.graph.versioned.v1` topic's production AsyncAPI-catalog wiring
(`events.EventEnvelopeBuilderPort` isolates that — see `events.py` module
docstring), consumption of `site.inventory.completed.v1` (upstream event
wiring is a later integration unit's job, not this builder's), any
outcome/DiD/causal/lift/KPI-weight computation (FORBIDDEN in W4 per mission
constraints — this package performs registration/derivation only).

Public API:
    FirstPartyMaterial / MaterialSourceKind / IntentLabel / FunnelStage /
        QueryCluster / DemandGraph
    build_demand_graph / compute_graph_version / compute_provenance_ref
    build_demand_graph_versioned_payload / emit_demand_graph_versioned_event
        / EventEnvelopeBuilderPort / DEMAND_GRAPH_VERSIONED_EVENT_TYPE /
        DEMAND_GRAPH_PRODUCER
    InMemoryDemandGraphStore
    DemandGraphError and every specific error subclass
"""

from __future__ import annotations

from saena_demand_graph.builder import (
    build_demand_graph,
    compute_graph_version,
    compute_provenance_ref,
)
from saena_demand_graph.errors import (
    CrossTenantDemandGraphError,
    DemandGraphError,
    DemandGraphNotFoundError,
    EmptyMaterialSetError,
    EngineNotPermittedError,
    MaterialValidationError,
    UnknownIntentError,
)
from saena_demand_graph.events import (
    DEMAND_GRAPH_PRODUCER,
    DEMAND_GRAPH_VERSIONED_EVENT_TYPE,
    EventEnvelopeBuilderPort,
    build_demand_graph_versioned_payload,
    emit_demand_graph_versioned_event,
)
from saena_demand_graph.records import (
    DemandGraph,
    FirstPartyMaterial,
    FunnelStage,
    IntentLabel,
    MaterialSourceKind,
    QueryCluster,
)
from saena_demand_graph.store import InMemoryDemandGraphStore

__all__ = [
    "DEMAND_GRAPH_PRODUCER",
    "DEMAND_GRAPH_VERSIONED_EVENT_TYPE",
    "CrossTenantDemandGraphError",
    "DemandGraph",
    "DemandGraphError",
    "DemandGraphNotFoundError",
    "EmptyMaterialSetError",
    "EngineNotPermittedError",
    "EventEnvelopeBuilderPort",
    "FirstPartyMaterial",
    "FunnelStage",
    "InMemoryDemandGraphStore",
    "IntentLabel",
    "MaterialSourceKind",
    "MaterialValidationError",
    "QueryCluster",
    "UnknownIntentError",
    "build_demand_graph",
    "build_demand_graph_versioned_payload",
    "compute_graph_version",
    "compute_provenance_ref",
    "emit_demand_graph_versioned_event",
]
