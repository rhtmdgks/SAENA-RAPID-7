"""`events.py`: payload shape, port injection, and (where the real
generated `saena_schemas`/`saena_domain.events.factory` modules are
importable) round-trip validation against the REAL
`demand.graph.versioned.v1` contract.

**Forward-dependency note** (see `events.py` module docstring): as of this
patch unit, `saena_schemas.event.demand_graph_versioned_v1` /
`saena_domain.events.factory.EnvelopeFactory` land via a separate Wave-4
Stage-1 sibling unit (w4-10, Contracts Steward) that is NOT guaranteed
importable in every environment this test suite runs in (this package's own
`pyproject.toml` intentionally has no direct dependency on the AsyncAPI
catalog gaining that channel). The tests below are split into two groups:
(a) pure payload-shape tests that assert this module's OWN contract (exact
mission field list, no dependency on `saena_schemas` at all — these always
run); (b) a real-contract round-trip group, skipped with a clear reason if
`saena_schemas.event.demand_graph_versioned_v1` is not importable in the
current environment, so this suite is honest about what it can and cannot
prove in a given run rather than silently skipping without a visible
signal.
"""

from __future__ import annotations

import pytest
from demand_graph_factories import make_envelope_kwargs_recorder, make_materials_for_all_intents
from saena_demand_graph.builder import build_demand_graph
from saena_demand_graph.errors import MaterialValidationError
from saena_demand_graph.events import (
    DEMAND_GRAPH_PRODUCER,
    DEMAND_GRAPH_VERSIONED_EVENT_TYPE,
    build_demand_graph_versioned_payload,
    emit_demand_graph_versioned_event,
)
from saena_demand_graph.records import DemandGraph, FunnelStage, IntentLabel, QueryCluster


def _build_graph() -> DemandGraph:
    materials = make_materials_for_all_intents()
    return build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)


def test_payload_has_exactly_the_mission_field_list() -> None:
    graph = _build_graph()
    payload = build_demand_graph_versioned_payload(graph)
    assert set(payload.keys()) == {
        "project_id",
        "graph_version",
        "cluster_count",
        "provenance_ref",
    }


def test_payload_field_values_match_the_graph() -> None:
    graph = _build_graph()
    payload = build_demand_graph_versioned_payload(graph)
    assert payload["project_id"] == graph.project_id
    assert payload["graph_version"] == graph.graph_version
    assert payload["cluster_count"] == len(graph.clusters)
    assert payload["provenance_ref"] == graph.provenance_ref


def test_payload_never_carries_tenant_id_or_run_id() -> None:
    """ADR-0024(e): payload must not re-project envelope-level tenant_id/
    run_id — even before this reaches a real EnvelopeFactory call."""
    graph = _build_graph()
    payload = build_demand_graph_versioned_payload(graph)
    assert "tenant_id" not in payload
    assert "run_id" not in payload


def test_payload_never_carries_raw_cluster_content() -> None:
    """Mission: 'NO PII, secrets, or raw customer source in event
    payloads' — the payload must never inline cluster paraphrases/
    provenance_refs, only the graph-level summary fields."""
    graph = _build_graph()
    payload = build_demand_graph_versioned_payload(graph)
    serialized_keys = set(payload.keys())
    assert "clusters" not in serialized_keys
    assert "paraphrases" not in serialized_keys


def test_payload_rejects_zero_cluster_graph() -> None:
    empty_graph = DemandGraph(
        tenant_id="acme-inc",
        project_id="proj-1",
        graph_version="sha256:" + ("a" * 64),
        clusters=(),
        provenance_ref="sha256:" + ("b" * 64),
    )
    with pytest.raises(MaterialValidationError):
        build_demand_graph_versioned_payload(empty_graph)


def test_emit_calls_envelope_builder_port_with_expected_kwargs() -> None:
    graph = _build_graph()
    calls, fake_port = make_envelope_kwargs_recorder()
    envelope = emit_demand_graph_versioned_event(
        graph=graph, run_id="run-123", envelope_builder=fake_port
    )
    assert len(calls) == 1
    call = calls[0]
    assert call["producer"] == DEMAND_GRAPH_PRODUCER
    assert call["event_type"] == DEMAND_GRAPH_VERSIONED_EVENT_TYPE
    assert call["tenant_id"] == graph.tenant_id
    assert call["run_id"] == "run-123"
    assert call["payload"] == build_demand_graph_versioned_payload(graph)
    assert envelope["event_type"] == DEMAND_GRAPH_VERSIONED_EVENT_TYPE


def test_emit_idempotency_key_is_deterministic_and_scoped() -> None:
    graph = _build_graph()
    calls_1, fake_port_1 = make_envelope_kwargs_recorder()
    calls_2, fake_port_2 = make_envelope_kwargs_recorder()
    emit_demand_graph_versioned_event(graph=graph, run_id="run-123", envelope_builder=fake_port_1)
    emit_demand_graph_versioned_event(graph=graph, run_id="run-123", envelope_builder=fake_port_2)
    assert calls_1[0]["idempotency_key"] == calls_2[0]["idempotency_key"]
    assert graph.tenant_id in calls_1[0]["idempotency_key"]
    assert graph.project_id in calls_1[0]["idempotency_key"]
    assert graph.graph_version in calls_1[0]["idempotency_key"]


def test_emit_idempotency_key_changes_with_run_id() -> None:
    graph = _build_graph()
    calls_1, fake_port_1 = make_envelope_kwargs_recorder()
    calls_2, fake_port_2 = make_envelope_kwargs_recorder()
    emit_demand_graph_versioned_event(graph=graph, run_id="run-a", envelope_builder=fake_port_1)
    emit_demand_graph_versioned_event(graph=graph, run_id="run-b", envelope_builder=fake_port_2)
    assert calls_1[0]["idempotency_key"] != calls_2[0]["idempotency_key"]


def test_event_envelope_builder_port_is_structurally_satisfied_by_a_plain_function() -> None:
    """`events.EventEnvelopeBuilderPort` is a structural Protocol — any
    plain function matching its keyword shape satisfies it without
    inheritance (proves this port is truly duck-typed / adapter-agnostic,
    matching `saena_site_discovery.crawler.SiteCrawlerPort`'s Protocol
    discipline)."""

    def _minimal_port(
        *,
        producer: str,
        event_type: str,
        tenant_id: str,
        run_id: str,
        idempotency_key: str,
        payload: dict | None = None,
    ) -> dict:
        return {"ok": True}

    graph = _build_graph()
    result = emit_demand_graph_versioned_event(
        graph=graph, run_id="run-123", envelope_builder=_minimal_port
    )
    assert result == {"ok": True}


def _real_schemas_importable() -> bool:
    try:
        import saena_schemas.event.demand_graph_versioned_v1  # noqa: F401
    except ImportError:
        return False
    return True


def _real_factory_importable() -> bool:
    try:
        from saena_domain.events.factory import EnvelopeFactory  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _real_schemas_importable(),
    reason=(
        "saena_schemas.event.demand_graph_versioned_v1 is a w4-10 (Contracts "
        "Steward) deliverable on a separate Stage-1 exclusive path — not "
        "guaranteed importable in every environment this package's own "
        "pyproject.toml (which deliberately has no dependency on that "
        "channel landing) is tested in; skipped honestly rather than "
        "silently passing."
    ),
)
def test_payload_validates_against_the_real_generated_schema() -> None:
    import saena_schemas.event.demand_graph_versioned_v1 as generated

    graph = _build_graph()
    payload = build_demand_graph_versioned_payload(graph)
    validated = generated.DemandGraphVersionedV1Payload.model_validate(payload)
    # project_id/provenance_ref are generated pydantic RootModel wrappers
    # (see saena_domain.audit.chain._plain_str's docstring for why this
    # unwrap is necessary — `str(root_model)` renders "root='...'", not the
    # wrapped value).
    assert validated.project_id.root == graph.project_id
    assert validated.graph_version == graph.graph_version
    assert validated.cluster_count == len(graph.clusters)
    assert validated.provenance_ref.root == graph.provenance_ref


@pytest.mark.skipif(
    not (_real_schemas_importable() and _real_factory_importable()),
    reason=(
        "saena_domain.events.factory.EnvelopeFactory + the "
        "demand.graph.versioned.v1 AsyncAPI channel are w4-10 deliverables "
        "on a separate Stage-1 exclusive path — skipped honestly if not "
        "importable in the current environment (see events.py module "
        "docstring 'Isolated forward-dependency gap')."
    ),
)
def test_emit_with_the_real_envelope_factory_builds_a_valid_envelope() -> None:
    from saena_domain.events.factory import EnvelopeFactory

    graph = _build_graph()
    envelope = emit_demand_graph_versioned_event(
        graph=graph,
        run_id="01977c1e6e6d7c1cbf6f7a5b9c0d1e2f",
        envelope_builder=EnvelopeFactory.build_tenant_envelope,
    )
    assert envelope["event_type"] == DEMAND_GRAPH_VERSIONED_EVENT_TYPE
    assert envelope["context_type"] == "tenant"
    assert envelope["tenant_id"] == graph.tenant_id
    assert envelope["payload"] == build_demand_graph_versioned_payload(graph)


def test_query_cluster_and_funnel_are_reexported_for_convenience() -> None:
    # Smoke-check the package-level re-exports used elsewhere in this test
    # module (IntentLabel/FunnelStage/QueryCluster) actually resolve.
    assert IntentLabel.PRICING.value == "pricing"
    assert FunnelStage.CONSIDERATION.value == "consideration"
    assert QueryCluster is not None
