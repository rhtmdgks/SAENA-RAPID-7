"""Wave 4 composite synthetic E2E (w4-17) — the whole intelligence chain,
REAL components throughout, deterministically end-to-end, NO container.

    demand-graph builds query clusters
    -> chatgpt-observer browser-pool (fixture browser) captures observations
       for those queries
    -> observations stored via the artifact single gateway
       (`FakeArtifactGateway` — no raw content ever inline)
    -> citation-intelligence normalizes citations
    -> entity-resolution builds the entity graph
    -> claim-evidence ledger records claims+evidence (fail-closed
       publishability)
    -> QEEG projection rebuilt by replay
    -> experiment registration ledger anchors a registered experiment
       (REGISTRATION ONLY — no outcome/DiD/lift; `saena_domain.experiment`
       has no field/method that could carry one, pinned upstream by
       `tests/unit/domain_experiment/test_no_outcome_fields.py`)

Every module exercised here is the ACTUAL w4-02/03/04/05/08/09/10/11
production package (brought into this worktree read-only via `git checkout
wave4-intelligence -- <path>`, per this unit's own task instruction) — never
a hand-rolled stand-in for any of them. The only fakes in this whole chain
are the two the upstream units THEMSELVES ship as their own deterministic
unit-lane substitute for a real external dependency: `FixtureBrowserSession`
(chatgpt-observer's own fixture browser — never a live ChatGPT session) and
`FakeArtifactGateway` (chatgpt-observer's own in-memory single-gateway
stand-in for a real artifact-registry HTTP adapter, same "HTTP adapter is
integration/deploy glue, not this unit's job" carve-out
`saena_chatgpt_observer.artifact_gateway`'s own module docstring documents).

Container-backed companion: `tests/integration/intelligence_e2e/
test_composite_intelligence_clickhouse_e2e.py` additionally persists the
observation into a REAL ClickHouse container and asserts the SAME
deterministic hashes this module proves survive that round trip unchanged.
"""

from __future__ import annotations

import copy

import pytest
from intelligence_e2e_harness import (
    ENGINE_ID,
    RUN_ID,
    TENANT_1,
    TENANT_2,
    CompositeChainResult,
    build_entities,
    build_graph,
    run_composite_chain,
    verify_ledger,
    verify_ledger_chain,
)
from saena_claim_evidence.errors import CrossTenantLedgerAccessError
from saena_demand_graph.errors import CrossTenantDemandGraphError
from saena_demand_graph.store import InMemoryDemandGraphStore
from saena_domain.qeeg.errors import CrossTenantProjectionAccessError, UnknownClaimError
from saena_domain.qeeg.replay import publishability_of
from saena_entity_resolution.errors import CrossTenantEntityAccessError
from saena_entity_resolution.store import InMemoryEntityGraphStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chain_result() -> CompositeChainResult:
    return run_composite_chain(tenant_id=TENANT_1)


# ---------------------------------------------------------------------------
# Whole-chain narrative — every stage's REAL output, asserted in order.
# ---------------------------------------------------------------------------


class TestCompositeChainNarrative:
    def test_demand_graph_builds_query_clusters(self, chain_result: CompositeChainResult) -> None:
        graph = chain_result.graph
        assert graph.tenant_id == TENANT_1
        assert len(graph.clusters) == 1  # both materials share one pricing/en-US cluster
        cluster = graph.clusters[0]
        assert cluster.intent.value == "pricing"
        assert len(cluster.paraphrases) == 2
        assert graph.graph_version.startswith("sha256:")
        assert graph.provenance_ref.startswith("sha256:")

    def test_demand_graph_versioned_envelope_is_real_and_validated(
        self, chain_result: CompositeChainResult
    ) -> None:
        envelope = chain_result.demand_graph_envelope
        assert envelope["event_type"] == "demand.graph.versioned.v1"
        assert envelope["producer"] == "demand-graph-service"
        assert envelope["tenant_id"] == TENANT_1
        assert envelope["context_type"] == "tenant"
        assert envelope["payload"]["cluster_count"] == 1
        assert envelope["payload"]["graph_version"] == chain_result.graph.graph_version
        # ADR-0024(e)-1: payload never re-projects envelope-level identifiers.
        assert "tenant_id" not in envelope["payload"]
        assert "run_id" not in envelope["payload"]

    def test_observer_captures_one_observation_per_cluster_query(
        self, chain_result: CompositeChainResult
    ) -> None:
        run_result = chain_result.observation_run
        assert run_result.final_status.name == "SUCCEEDED"
        # 2 distinct paraphrases in the one cluster -> 2 observations.
        assert len(run_result.results) == 2
        for pooled in run_result.results:
            record = pooled.observation_record
            assert record["tenant_id"] == TENANT_1
            assert record["engine_id"] == ENGINE_ID
            # raw content NEVER inline — only opaque refs/hashes.
            assert "raw_content" not in record
            assert record["raw_object_ref"].startswith("artifact://")
            assert record["artifact_hash"].startswith("sha256:")
            envelope = pooled.observation_captured_envelope
            assert envelope["event_type"] == "observation.captured.v1"
            assert envelope["payload"]["engine_id"] == ENGINE_ID
            assert envelope["payload"]["artifact_hash"] == record["artifact_hash"]
            # engine-required payload never carries raw_object_ref either.
            assert "raw_object_ref" not in envelope["payload"]

    def test_citation_intelligence_normalizes_the_observed_citation(
        self, chain_result: CompositeChainResult
    ) -> None:
        assert len(chain_result.citation_results) == 2
        first = chain_result.citation_results[0]
        assert first.record.normalized_uri == "https://acme-w4e2e.example.com/pricing"
        assert first.record.ownership_class.value == "owned"
        envelope = first.envelope
        assert envelope["event_type"] == "citation.normalized.v1"
        assert envelope["payload"]["engine_id"] == ENGINE_ID
        assert envelope["payload"]["content_hash"] == first.record.content_hash

    def test_entity_resolution_builds_owned_and_competitor_entities(
        self, chain_result: CompositeChainResult
    ) -> None:
        graph = chain_result.entity_graph
        assert graph.tenant_id == TENANT_1
        assert graph.entity_count == 2
        by_id = {e.entity_id: e for e in graph.entities}
        assert by_id["entity-w4e2e-brand"].entity_type.value == "brand"
        assert by_id["entity-w4e2e-competitor"].entity_type.value == "competitor"
        # provenance anchors to the UPSTREAM demand-graph's own graph_version.
        assert graph.provenance_ref == chain_result.graph.graph_version

    def test_entity_graph_versioned_envelope_is_real_and_validated(
        self, chain_result: CompositeChainResult
    ) -> None:
        envelope = chain_result.entity_graph_envelope
        assert envelope["event_type"] == "entity.graph.versioned.v1"
        assert envelope["payload"]["entity_count"] == 2
        assert envelope["payload"]["provenance_ref"] == chain_result.entity_graph.provenance_ref

    def test_vector_store_upserts_entities_and_finds_self_as_nearest_neighbor(
        self, chain_result: CompositeChainResult
    ) -> None:
        assert len(chain_result.vector_upserted) == 2
        (nearest, *_rest) = chain_result.vector_search_hits
        assert nearest.record.record_id == "entity-w4e2e-brand"
        assert nearest.record.tenant_id == TENANT_1
        assert nearest.distance == pytest.approx(0.0, abs=1e-9)
        assert nearest.record.source_snapshot_hash == chain_result.entity_graph.graph_version

    def test_claim_evidence_ledger_is_fail_closed_publishable(
        self, chain_result: CompositeChainResult
    ) -> None:
        ledger_state = chain_result.claim_evidence_build.ledger_state
        ok, first_broken = verify_ledger_chain(ledger_state)
        assert ok is True
        assert first_broken is None
        # claim linked to fresh, LINKED evidence -> publishable.
        assert ledger_state[-1].kind == "claim"
        assert ledger_state[-1].publishability.publishable is True
        assert ledger_state[-1].publishability.blocking_reasons == ()

    def test_claim_evidence_versioned_envelope_is_real_and_validated(
        self, chain_result: CompositeChainResult
    ) -> None:
        envelope = chain_result.claim_evidence_envelope
        assert envelope["event_type"] == "claim.evidence.versioned.v1"
        assert envelope["payload"]["claim_count"] == 1
        assert envelope["payload"]["evidence_count"] == 1

    def test_qeeg_projection_replays_the_same_publishability_the_ledger_decided(
        self, chain_result: CompositeChainResult
    ) -> None:
        state = chain_result.qeeg_state
        claim = chain_result.claim_evidence_build.claim
        view = publishability_of(state, claim.claim_id)
        assert view.publishable is True
        assert view.blocking_reasons == ()
        assert view.evidence_ids == (chain_result.claim_evidence_build.evidence.evidence_id,)
        # QEEG never reads claim_text/excerpt (no PII) — only ids/facts.
        dump = repr(state)
        assert chain_result.claim_evidence_build.claim.claim_text not in dump
        assert chain_result.claim_evidence_build.evidence.excerpt not in dump

    def test_experiment_registration_ledger_anchors_registration_only(
        self, chain_result: CompositeChainResult
    ) -> None:
        entry = chain_result.experiment_entry
        ok, bad_index = verify_ledger(chain_result.experiment_ledger)
        assert ok is True
        assert bad_index is None
        assert entry.canonical_hash is not None
        assert entry.canonical_hash.startswith("sha256:")
        assert entry.previous_hash is None  # first entry in a fresh ledger anchors to GENESIS

        # Registration-only, hard-checked at the FIELD-NAME level (no
        # outcome/effect/lift/DiD field exists anywhere on this model —
        # mirrors tests/unit/domain_experiment/test_no_outcome_fields.py's
        # own executable pin, re-asserted here at the E2E boundary).
        from saena_domain.experiment.models import FORBIDDEN_OUTCOME_TOKENS

        field_names = set(type(entry).model_fields)
        for token in FORBIDDEN_OUTCOME_TOKENS:
            assert not any(token in name.lower() for name in field_names), token

    def test_experiment_registered_and_anchored_envelopes_are_real_and_validated(
        self, chain_result: CompositeChainResult
    ) -> None:
        registered = chain_result.experiment_registered_envelope
        anchored = chain_result.experiment_anchored_envelope
        assert registered["event_type"] == "experiment.registered.v1"
        assert anchored["event_type"] == "experiment.anchored.v1"
        for envelope in (registered, anchored):
            assert envelope["producer"] == "experiment-attribution-service"
            assert envelope["payload"]["engine_id"] == ENGINE_ID
            assert (
                envelope["payload"]["experiment_id"] == chain_result.experiment_entry.experiment_id
            )
            assert (
                envelope["payload"]["canonical_hash"]
                == chain_result.experiment_entry.canonical_hash
            )
        assert anchored["payload"]["previous_hash"] is None


# ---------------------------------------------------------------------------
# Determinism — identical synthetic input -> identical hashes/graph_versions
# across two independent runs of the WHOLE chain.
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_whole_chain_run_twice_yields_identical_hashes(self) -> None:
        run_a = run_composite_chain(tenant_id=TENANT_1)
        run_b = run_composite_chain(tenant_id=TENANT_1)

        assert run_a.graph.graph_version == run_b.graph.graph_version
        assert run_a.graph.provenance_ref == run_b.graph.provenance_ref
        assert run_a.entity_graph.graph_version == run_b.entity_graph.graph_version
        assert (
            run_a.claim_evidence_build.ledger_state[-1].canonical_hash
            == run_b.claim_evidence_build.ledger_state[-1].canonical_hash
        )
        assert run_a.qeeg_state == run_b.qeeg_state
        assert run_a.experiment_entry.canonical_hash == run_b.experiment_entry.canonical_hash

        # Every observation's artifact_hash is a pure function of its fixture
        # response content -> identical across runs too.
        hashes_a = [r.artifact_hash for r in run_a.observation_run.results]
        hashes_b = [r.artifact_hash for r in run_b.observation_run.results]
        assert hashes_a == hashes_b

        # TestEmbedder is a pure function of (seed, model, version, text) ->
        # identical vectors across runs, so the nearest-neighbor hit is
        # identical too.
        assert (
            run_a.vector_search_hits[0].record.vector == run_b.vector_search_hits[0].record.vector
        )

    def test_envelope_payloads_are_deep_equal_across_two_runs(self) -> None:
        """Every envelope's `payload` (the caller-controlled, hash-derived
        content) matches byte-for-byte across two independent runs. The
        envelope's own per-call identity fields (`event_id` always,
        `occurred_at`/`trace_id` too for `demand.graph.versioned.v1`/
        `entity.graph.versioned.v1` specifically — neither
        `emit_demand_graph_versioned_event` nor
        `build_entity_graph_versioned_envelope` exposes an `occurred_at`/
        `trace_id` pin, unlike `build_claim_evidence_versioned_event` and
        this harness's own direct `EnvelopeFactory` calls for the experiment
        events) are exactly the parts `EnvelopeFactory` itself always
        freshly synthesizes per call — this test scopes its equality
        assertion to `payload` alone for that reason, and separately checks
        full-envelope equality (identity fields included) for the three
        envelopes this harness pins `occurred_at`/`trace_id` on."""
        run_a = run_composite_chain(tenant_id=TENANT_1)
        run_b = run_composite_chain(tenant_id=TENANT_1)

        for env_a, env_b in (
            (run_a.demand_graph_envelope, run_b.demand_graph_envelope),
            (run_a.entity_graph_envelope, run_b.entity_graph_envelope),
            (run_a.claim_evidence_envelope, run_b.claim_evidence_envelope),
            (run_a.experiment_registered_envelope, run_b.experiment_registered_envelope),
            (run_a.experiment_anchored_envelope, run_b.experiment_anchored_envelope),
        ):
            assert env_a["payload"] == env_b["payload"]
            assert env_a["tenant_id"] == env_b["tenant_id"]
            assert env_a["event_type"] == env_b["event_type"]
            assert env_a["producer"] == env_b["producer"]

        for env_a, env_b in (
            (run_a.claim_evidence_envelope, run_b.claim_evidence_envelope),
            (run_a.experiment_registered_envelope, run_b.experiment_registered_envelope),
            (run_a.experiment_anchored_envelope, run_b.experiment_anchored_envelope),
        ):
            stripped_a = copy.deepcopy(env_a)
            stripped_b = copy.deepcopy(env_b)
            del stripped_a["event_id"]
            del stripped_b["event_id"]
            assert stripped_a == stripped_b


# ---------------------------------------------------------------------------
# Engine scope — chatgpt-search stays the ONLY engine anywhere in the chain.
# ---------------------------------------------------------------------------


class TestEngineScope:
    def test_every_engine_required_envelope_pins_chatgpt_search(
        self, chain_result: CompositeChainResult
    ) -> None:
        for pooled in chain_result.observation_run.results:
            assert pooled.observation_captured_envelope["payload"]["engine_id"] == "chatgpt-search"
        for citation_result in chain_result.citation_results:
            assert citation_result.envelope["payload"]["engine_id"] == "chatgpt-search"
        assert (
            chain_result.experiment_registered_envelope["payload"]["engine_id"] == "chatgpt-search"
        )
        assert chain_result.experiment_anchored_envelope["payload"]["engine_id"] == "chatgpt-search"

    def test_disallowed_engine_is_rejected_at_the_observer_boundary(self) -> None:
        from intelligence_e2e_harness import job_context
        from saena_chatgpt_observer.artifact_gateway import FakeArtifactGateway
        from saena_chatgpt_observer.pool import BrowserPool, FixtureBrowserSessionFactory
        from saena_chatgpt_observer.pool_capture import run_pooled_observation
        from saena_domain.execution.errors import (
            EngineNotPermittedError as ObserverEngineNotPermittedError,
        )

        pool = BrowserPool(
            FixtureBrowserSessionFactory(shared_responses={"q": b"<html></html>"}), max_size=1
        )
        with pytest.raises(ObserverEngineNotPermittedError):
            run_pooled_observation(
                job_context=job_context(),
                pool=pool,
                artifact_gateway=FakeArtifactGateway(),
                engine_id="gemini",
                queries=["q"],
            )

    def test_disallowed_engine_is_rejected_at_the_citation_boundary(self) -> None:
        from saena_citation_intelligence.errors import EngineNotPermittedError
        from saena_citation_intelligence.service import normalize_citation

        with pytest.raises(EngineNotPermittedError):
            normalize_citation(
                tenant_id=TENANT_1,
                run_id=RUN_ID,
                citation_id="cite-disallowed",
                raw_url="https://example.com/x",
                engine_id="google-ai-overviews",
            )


# ---------------------------------------------------------------------------
# Tenant isolation — a second tenant sees NOTHING of tenant one's chain, at
# every stage, both via direct storage adapters and via cross-tenant replay.
# ---------------------------------------------------------------------------


class TestTenantIsolationEndToEnd:
    def test_second_tenant_produces_an_entirely_independent_chain(self) -> None:
        run_1 = run_composite_chain(tenant_id=TENANT_1)
        run_2 = run_composite_chain(tenant_id=TENANT_2)

        assert run_1.graph.tenant_id == TENANT_1
        assert run_2.graph.tenant_id == TENANT_2
        # Same synthetic material content, different tenant_id -> different
        # graph_version (tenant_id is hashed material, per builder.py).
        assert run_1.graph.graph_version != run_2.graph.graph_version
        assert run_1.entity_graph.graph_version != run_2.entity_graph.graph_version

        for pooled in run_2.observation_run.results:
            assert pooled.observation_record["tenant_id"] == TENANT_2

    def test_demand_graph_store_denies_cross_tenant_read(self) -> None:
        store = InMemoryDemandGraphStore()
        graph_1 = build_graph(tenant_id=TENANT_1)
        store.put(TENANT_1, graph_1.project_id, graph_1)

        with pytest.raises(CrossTenantDemandGraphError):
            store.put(TENANT_2, graph_1.project_id, graph_1)

        from saena_demand_graph.errors import DemandGraphNotFoundError

        with pytest.raises(DemandGraphNotFoundError):
            store.get(TENANT_2, graph_1.project_id)

    def test_entity_graph_store_denies_cross_tenant_read(self) -> None:
        store = InMemoryEntityGraphStore()
        graph_1 = build_entities(build_graph(tenant_id=TENANT_1), tenant_id=TENANT_1)
        store.put(TENANT_1, graph_1.project_id, graph_1)

        with pytest.raises(CrossTenantEntityAccessError):
            graph_1.entities_owned_by_tenant(TENANT_2)

        from saena_entity_resolution.errors import EntityGraphNotFoundError

        with pytest.raises(EntityGraphNotFoundError):
            store.get(TENANT_2, graph_1.project_id)

    def test_vector_store_denies_a_forged_cross_tenant_upsert(
        self, chain_result: CompositeChainResult
    ) -> None:
        import asyncio

        from intelligence_e2e_harness import entity_vector_records
        from saena_vector_store import InMemoryVectorStore
        from saena_vector_store.errors import TenantIsolationError

        store = InMemoryVectorStore()
        records = entity_vector_records(chain_result.entity_graph, tenant_id=TENANT_1)
        with pytest.raises(TenantIsolationError):
            asyncio.run(store.upsert(TENANT_2, records))

    def test_vector_store_search_never_returns_another_tenants_vector(
        self, chain_result: CompositeChainResult
    ) -> None:
        import asyncio

        from intelligence_e2e_harness import VECTOR_COLLECTION, embedder, entity_vector_records
        from saena_vector_store import InMemoryVectorStore

        store = InMemoryVectorStore()
        records_1 = entity_vector_records(chain_result.entity_graph, tenant_id=TENANT_1)
        emb = embedder()

        async def _scenario() -> tuple[object, ...]:
            await store.upsert(TENANT_1, records_1)
            # tenant 2 searches with the SAME vector tenant 1's brand entity
            # embeds to — a numerically-identical vector must still never
            # surface tenant 1's record under tenant 2's own search.
            return await store.search(
                TENANT_2, VECTOR_COLLECTION, emb.embed_vector("Acme W4E2E"), 5
            )

        hits = asyncio.run(_scenario())
        assert hits == ()

    def test_claim_evidence_store_denies_cross_tenant_append(
        self, chain_result: CompositeChainResult
    ) -> None:
        from saena_claim_evidence.store import InMemoryClaimEvidenceStore

        store = InMemoryClaimEvidenceStore()
        with pytest.raises(CrossTenantLedgerAccessError):
            store.append_claim(TENANT_2, chain_result.claim_evidence_build.claim)

    def test_qeeg_projection_denies_cross_tenant_publishability_read(
        self, chain_result: CompositeChainResult
    ) -> None:
        from intelligence_e2e_harness import replay_qeeg

        state_tenant_2 = replay_qeeg(chain_result.claim_evidence_build, tenant_id=TENANT_2)
        with pytest.raises(UnknownClaimError):
            publishability_of(state_tenant_2, chain_result.claim_evidence_build.claim.claim_id)

    def test_qeeg_replay_denies_a_foreign_tenant_fact_outright(
        self, chain_result: CompositeChainResult
    ) -> None:
        from saena_domain.qeeg.models import ClaimFact
        from saena_domain.qeeg.replay import apply_claim_fact, empty_projection

        state = empty_projection(TENANT_1)
        foreign_fact = ClaimFact(
            tenant_id=TENANT_2,
            project_id="w4e2e-project-one",
            claim_id="claim-foreign",
            entity_id="entity-foreign",
            status="active",
            publishable=True,
            blocking_reasons=(),
            supporting_evidence_ids=(),
        )
        with pytest.raises(CrossTenantProjectionAccessError):
            apply_claim_fact(state, foreign_fact)

    def test_experiment_ledger_registration_is_tenant_scoped_by_content(self) -> None:
        """The experiment ledger itself carries no store/adapter (it is a
        pure append-only value sequence, `saena_domain.experiment.ledger`
        module docstring) — tenant scoping is enforced by the CONTENT of
        each `ExperimentRegistration.tenant_id` field, proven here by
        registering the SAME experiment_id under two different tenants and
        confirming each entry keeps its own tenant_id, never silently
        merged."""
        run_1 = run_composite_chain(tenant_id=TENANT_1)
        run_2 = run_composite_chain(tenant_id=TENANT_2)
        assert run_1.experiment_entry.tenant_id == TENANT_1
        assert run_2.experiment_entry.tenant_id == TENANT_2
        assert run_1.experiment_entry.canonical_hash != run_2.experiment_entry.canonical_hash
