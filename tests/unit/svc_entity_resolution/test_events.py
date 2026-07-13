"""Unit tests: `saena_entity_resolution.events` — `entity.graph.versioned.v1`
payload/envelope emission validity."""

from __future__ import annotations

import pytest
from saena_entity_resolution.canonicalize import AliasGroup, EntityType
from saena_entity_resolution.events import (
    EntityGraphEventValidationError,
    build_entity_graph_versioned_envelope,
    build_entity_graph_versioned_payload,
)
from saena_entity_resolution.graph import build_entity_graph
from saena_schemas.event.entity_graph_versioned_v1 import EntityGraphVersionedV1Payload

_PROVENANCE_REF = "sha256:" + "d" * 64


def _graph(tenant_id: str = "acme-corp", project_id: str = "proj-1"):
    groups = (
        AliasGroup(
            entity_id="e1",
            entity_type=EntityType.brand,
            canonical_name="Acme",
            aliases=("acme",),
            is_owned=True,
        ),
        AliasGroup(
            entity_id="e2",
            entity_type=EntityType.competitor,
            canonical_name="Rival",
            aliases=("rival",),
            is_owned=False,
        ),
    )
    return build_entity_graph(
        tenant_id=tenant_id,
        project_id=project_id,
        alias_groups=groups,
        provenance_ref=_PROVENANCE_REF,
    )


class TestPayloadBuilder:
    def test_payload_has_exactly_the_four_mission_fields(self) -> None:
        payload = build_entity_graph_versioned_payload(_graph())
        assert set(payload) == {"project_id", "graph_version", "entity_count", "provenance_ref"}

    def test_payload_validates_against_generated_model(self) -> None:
        payload = build_entity_graph_versioned_payload(_graph())
        # Must not raise.
        EntityGraphVersionedV1Payload.model_validate(payload)

    def test_payload_entity_count_matches_graph(self) -> None:
        graph = _graph()
        payload = build_entity_graph_versioned_payload(graph)
        assert payload["entity_count"] == graph.entity_count == 2

    def test_payload_carries_project_id_not_tenant_id(self) -> None:
        payload = build_entity_graph_versioned_payload(_graph())
        assert "tenant_id" not in payload
        assert payload["project_id"] == "proj-1"

    def test_payload_graph_version_matches_graph(self) -> None:
        graph = _graph()
        payload = build_entity_graph_versioned_payload(graph)
        assert payload["graph_version"] == graph.graph_version

    def test_payload_provenance_ref_matches_graph(self) -> None:
        graph = _graph()
        payload = build_entity_graph_versioned_payload(graph)
        assert payload["provenance_ref"] == graph.provenance_ref

    def test_zero_entity_graph_produces_valid_payload(self) -> None:
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-empty",
            alias_groups=(),
            provenance_ref=_PROVENANCE_REF,
        )
        payload = build_entity_graph_versioned_payload(graph)
        assert payload["entity_count"] == 0

    def test_malformed_provenance_ref_raises_event_validation_error(self) -> None:
        # `EntityGraph.provenance_ref` is a plain str field (not itself
        # schema-pattern-constrained at construction) — the payload builder
        # is the enforcement point for the sha256_ref wire-shape contract.
        # This exercises that fail-closed guard directly.
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=(),
            provenance_ref="not-a-sha256-ref",
        )
        with pytest.raises(EntityGraphEventValidationError) as excinfo:
            build_entity_graph_versioned_payload(graph)
        assert excinfo.value.context["project_id"] == "proj-1"


class TestEnvelopeBuilder:
    def test_envelope_is_tenant_context(self) -> None:
        graph = _graph()
        envelope = build_entity_graph_versioned_envelope(
            graph, run_id="run-1", idempotency_key="acme-corp:proj-1:v1"
        )
        assert envelope["context_type"] == "tenant"
        assert envelope["tenant_id"] == "acme-corp"
        assert envelope["run_id"] == "run-1"

    def test_envelope_event_type_and_producer(self) -> None:
        envelope = build_entity_graph_versioned_envelope(
            _graph(), run_id="run-1", idempotency_key="key-1"
        )
        assert envelope["event_type"] == "entity.graph.versioned.v1"
        assert envelope["producer"] == "entity-resolution-service"

    def test_envelope_payload_matches_standalone_payload_builder(self) -> None:
        graph = _graph()
        envelope = build_entity_graph_versioned_envelope(
            graph, run_id="run-1", idempotency_key="key-1"
        )
        assert envelope["payload"] == build_entity_graph_versioned_payload(graph)

    def test_envelope_never_carries_engine_id(self) -> None:
        # entity.graph.versioned.v1 is NOT one of the 3 engine_id-required
        # channels (observation/citation/experiment-outcome families) — the
        # envelope must never require or silently inject one.
        envelope = build_entity_graph_versioned_envelope(
            _graph(), run_id="run-1", idempotency_key="key-1"
        )
        assert "engine_id" not in envelope["payload"]

    def test_envelope_carries_no_pii_or_secret_shaped_fields(self) -> None:
        envelope = build_entity_graph_versioned_envelope(
            _graph(), run_id="run-1", idempotency_key="key-1"
        )
        forbidden_substrings = ("email", "password", "secret", "token", "ssn", "api_key")
        flattened = str(envelope).lower()
        for token in forbidden_substrings:
            assert token not in flattened

    def test_envelope_idempotency_key_is_caller_supplied(self) -> None:
        envelope = build_entity_graph_versioned_envelope(
            _graph(), run_id="run-1", idempotency_key="my-custom-key"
        )
        assert envelope["idempotency_key"] == "my-custom-key"

    def test_different_tenants_produce_independently_valid_envelopes(self) -> None:
        envelope_a = build_entity_graph_versioned_envelope(
            _graph(tenant_id="tenant-a"), run_id="run-1", idempotency_key="key-a"
        )
        envelope_b = build_entity_graph_versioned_envelope(
            _graph(tenant_id="tenant-b"), run_id="run-1", idempotency_key="key-b"
        )
        assert envelope_a["tenant_id"] == "tenant-a"
        assert envelope_b["tenant_id"] == "tenant-b"
        assert envelope_a["tenant_id"] != envelope_b["tenant_id"]
