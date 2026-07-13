"""Shared constants + builder helpers for `tests/e2e/intelligence` (w4-17).

Deliberately NOT named `conftest.py` — a second `conftest.py` in a sibling
test directory collides under pytest's default `prepend` import mode (see
`tests/e2e/execution/execution_e2e_harness.py`'s own module docstring for
the full rationale this repo has already hit more than once; the same
uniquely-named-module discipline is applied here).

This module has NO pytest fixtures of its own — only plain constants and
pure builder functions the two test modules in this package (`tests/e2e/
intelligence/test_composite_intelligence_e2e.py` and `tests/integration/
intelligence_e2e/test_composite_intelligence_clickhouse_e2e.py`) both call,
so the exact same synthetic-input recipe drives both the pure-synthetic and
the ClickHouse-backed lane (their outputs are asserted to be
hash-for-hash IDENTICAL, which only holds if both lanes build from the
IDENTICAL synthetic material below — never two independently-typed-out
fixture sets that could silently drift apart).

Composite chain this package exercises end-to-end, REAL components
throughout (no mock-only chain — every module below is the actual w4-02..
w4-11 production package, never a hand-rolled stand-in):

    demand-graph (query clusters)
      -> chatgpt-observer browser-pool (fixture browser; observations per
         cluster's own paraphrase queries)
      -> citation-intelligence (normalizes one citation ref per observation)
      -> entity-resolution (brand/competitor entity graph)
      -> claim-evidence ledger (claims + evidence, fail-closed publishability)
      -> QEEG projection (read-only replay over the claim-evidence ledger)
      -> experiment registration ledger (registration ONLY — anchors a
         registered experiment; NO outcome/DiD/lift/absorption/strategy-card
         anywhere in this package, per CLAUDE.md Wave-4 hard constraints)

Every step is deterministic (injected clock/ids, no wall-clock/random/
network) and tenant-scoped (every builder takes an explicit `tenant_id` and
every downstream store/ledger enforces its own cross-tenant default-DENY —
this module never bypasses any of those checks, it only supplies
already-tenant-correct input).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from saena_chatgpt_observer.artifact_gateway import FakeArtifactGateway
from saena_chatgpt_observer.pool import BrowserPool, FixtureBrowserSessionFactory
from saena_chatgpt_observer.pool_capture import PooledObservationRunResult, run_pooled_observation
from saena_citation_intelligence.service import CitationNormalizationResult, normalize_citation
from saena_claim_evidence import (
    ClaimEvidenceLedgerState,
    EvidenceFreshnessPolicy,
    EvidenceLinkStatus,
    append_claim,
    append_evidence,
    build_claim_evidence_versioned_event,
    verify_ledger_chain,
)
from saena_claim_evidence.qeeg_projection import build_qeeg_projection
from saena_demand_graph import (
    DemandGraph,
    FirstPartyMaterial,
    MaterialSourceKind,
    build_demand_graph,
    emit_demand_graph_versioned_event,
)
from saena_domain.events import EnvelopeFactory
from saena_domain.execution import JobContext
from saena_domain.experiment.ledger import LedgerState, register, verify_ledger
from saena_domain.experiment.models import ExperimentArm, ExperimentRegistration, MetricDefinition
from saena_domain.qeeg import QeegProjectionState
from saena_entity_resolution import (
    AliasGroup,
    EntityGraph,
    EntityType,
    build_entity_graph,
    build_entity_graph_versioned_envelope,
)
from saena_schemas.domain.evidence_record_v1 import EvidenceRecord
from saena_schemas.domain.extracted_claim_v1 import ExtractedClaim
from saena_vector_store import InMemoryVectorStore, TestEmbedder, VectorRecord

# ---------------------------------------------------------------------------
# Tenant / run identity — two tenants prove end-to-end isolation.
# ---------------------------------------------------------------------------

TENANT_1 = "w4e2e-tenant-one"
TENANT_2 = "w4e2e-tenant-two"
PROJECT_1 = "w4e2e-project-one"
RUN_ID = "run-w4e2e-0001"
ENGINE_ID = "chatgpt-search"
ACTOR_ID = "actor-w4e2e-01"

#: Fixed clock every builder below is injected with — no wall-clock read
#: anywhere in this package, matching every upstream module's own
#: `clock: Callable[[], str]` determinism-injection discipline.
FIXED_TIMESTAMP = "2026-07-13T00:00:00Z"


def fixed_clock() -> str:
    return FIXED_TIMESTAMP


def job_context(*, tenant_id: str = TENANT_1, run_id: str = RUN_ID) -> JobContext:
    return JobContext(
        tenant_id=tenant_id,
        workspace_id="ws-w4e2e-0001",
        project_id=PROJECT_1,
        run_id=run_id,
        trace_id="a" * 32,
        idempotency_key=f"{tenant_id}:{run_id}:w4-17",
        actor_id=ACTOR_ID,
    )


# ---------------------------------------------------------------------------
# Stage 1 — demand-graph: query clusters from approved first-party material.
# ---------------------------------------------------------------------------


def first_party_materials(*, tenant_prefix: str = "m") -> list[FirstPartyMaterial]:
    """Two first-party materials that resolve to the SAME `pricing` intent
    cluster (`en-US`) — deterministic, offline, no scraped/external content
    (mission constraint enforced at the type level by `MaterialSourceKind`
    itself never carrying an external member)."""
    return [
        FirstPartyMaterial(
            material_id=f"{tenant_prefix}-1",
            source_kind=MaterialSourceKind.SALES_TRANSCRIPT,
            text="what is your pricing plan",
            locale="en-US",
            provenance_ref="doc://sales/call-w4e2e-1",
        ),
        FirstPartyMaterial(
            material_id=f"{tenant_prefix}-2",
            source_kind=MaterialSourceKind.SUPPORT_TICKET,
            text="what is the cost of a plan",
            locale="en-US",
            provenance_ref="doc://support/ticket-w4e2e-1",
        ),
    ]


def build_graph(*, tenant_id: str = TENANT_1) -> DemandGraph:
    return build_demand_graph(
        tenant_id=tenant_id, project_id=PROJECT_1, materials=first_party_materials()
    )


def demand_graph_envelope(graph: DemandGraph) -> dict[str, Any]:
    """The REAL `demand.graph.versioned.v1` envelope, built via the REAL
    `EnvelopeFactory` (w4-10 registered the channel — see `events.py`'s own
    module docstring for the isolated-forward-dependency history this
    now resolves)."""
    return emit_demand_graph_versioned_event(
        graph=graph, run_id=RUN_ID, envelope_builder=EnvelopeFactory.build_tenant_envelope
    )


# ---------------------------------------------------------------------------
# Stage 2 — chatgpt-observer browser-pool: one observation per cluster
# paraphrase query, fixture browser only (no live ChatGPT, no external creds).
# ---------------------------------------------------------------------------


def cluster_queries(graph: DemandGraph) -> list[str]:
    """Every distinct paraphrase across `graph`'s clusters, in the graph's
    own deterministic cluster/paraphrase order — these become the observer's
    `queries` argument, so demand-graph output DIRECTLY drives what the
    observer captures (never a hand-typed, independently-chosen query list)."""
    queries: list[str] = []
    for cluster in graph.clusters:
        for paraphrase in cluster.paraphrases:
            if paraphrase not in queries:
                queries.append(paraphrase)
    return queries


def fixture_responses(queries: list[str]) -> dict[str, bytes]:
    """Deterministic canned HTML per query — content is a pure function of
    the query text itself, so two runs over the same demand graph always
    produce byte-identical raw responses (and therefore byte-identical
    `artifact_hash`es)."""
    return {
        query: f"<html><body>chatgpt-search result for: {query}</body></html>".encode()
        for query in queries
    }


def run_observations(
    graph: DemandGraph, *, tenant_id: str = TENANT_1
) -> PooledObservationRunResult:
    queries = cluster_queries(graph)
    pool = BrowserPool(
        FixtureBrowserSessionFactory(shared_responses=fixture_responses(queries)), max_size=2
    )
    gateway = FakeArtifactGateway()
    return run_pooled_observation(
        job_context=job_context(tenant_id=tenant_id),
        pool=pool,
        artifact_gateway=gateway,
        engine_id=ENGINE_ID,
        queries=queries,
        citation_extractor=lambda raw_content: (  # noqa: ARG005
            "https://acme-w4e2e.example.com/pricing",
        ),
        observation_id_factory=lambda run_id, i: f"{run_id}-obs-{i:04d}",
        clock=fixed_clock,
    )


# ---------------------------------------------------------------------------
# Stage 3 — citation-intelligence: normalize one citation per observation.
# ---------------------------------------------------------------------------

OWNED_DOMAINS: frozenset[str] = frozenset({"acme-w4e2e.example.com"})
COMPETITOR_DOMAINS: frozenset[str] = frozenset({"rival-w4e2e.example.com"})


def normalize_observation_citations(
    observation_run: PooledObservationRunResult, *, tenant_id: str = TENANT_1
) -> list[CitationNormalizationResult]:
    results: list[CitationNormalizationResult] = []
    for index, pooled_result in enumerate(observation_run.results):
        (raw_citation,) = pooled_result.observation_record["citation_refs"]
        results.append(
            normalize_citation(
                tenant_id=tenant_id,
                run_id=RUN_ID,
                citation_id=f"cite-w4e2e-{index:04d}",
                raw_url=raw_citation,
                engine_id=ENGINE_ID,
                tenant_owned_domains=OWNED_DOMAINS,
                competitor_domains=COMPETITOR_DOMAINS,
                clock=fixed_clock,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Stage 4 — entity-resolution: brand (owned) + competitor entity graph.
# ---------------------------------------------------------------------------


def alias_groups() -> tuple[AliasGroup, ...]:
    return (
        AliasGroup(
            entity_id="entity-w4e2e-brand",
            entity_type=EntityType.brand,
            canonical_name="Acme W4E2E",
            aliases=("Acme", "acme w4e2e", "ACME"),
            is_owned=True,
        ),
        AliasGroup(
            entity_id="entity-w4e2e-competitor",
            entity_type=EntityType.competitor,
            canonical_name="Rival W4E2E",
            aliases=("rival", "Rival Co"),
            is_owned=False,
        ),
    )


def build_entities(graph: DemandGraph, *, tenant_id: str = TENANT_1) -> EntityGraph:
    """`provenance_ref` anchors to the UPSTREAM demand graph's own
    `graph_version` — one real cross-module provenance chain, not an
    independently-invented hash (mirrors `graph.build_entity_graph`'s own
    docstring: "a source snapshot hash, an upstream `demand.graph.
    versioned.v1.graph_version`, ...")."""
    return build_entity_graph(
        tenant_id=tenant_id,
        project_id=PROJECT_1,
        alias_groups=alias_groups(),
        provenance_ref=graph.graph_version,
        clock=fixed_clock,
    )


def entity_graph_envelope(graph: EntityGraph) -> dict[str, Any]:
    return build_entity_graph_versioned_envelope(
        graph,
        run_id=RUN_ID,
        idempotency_key=f"{graph.tenant_id}:{PROJECT_1}:{graph.graph_version}",
    )


# ---------------------------------------------------------------------------
# Stage 4.5 — vector-store: embed + upsert each resolved entity, then run an
# ANN search — deterministic `TestEmbedder` (no network/external provider),
# `InMemoryVectorStore` (genuinely satisfies the same async `VectorStore`
# Protocol `PgVectorStore` does; see `saena_vector_store.memory` module
# docstring), so this whole stage stays container-free in the pure-synthetic
# lane while still exercising the REAL port + REAL backend, unmodified.
# ---------------------------------------------------------------------------

VECTOR_COLLECTION = "w4e2e-entities"


def embedder() -> TestEmbedder:
    return TestEmbedder(dimension=8, seed=0)


def entity_vector_records(
    entity_graph: EntityGraph, *, tenant_id: str = TENANT_1
) -> tuple[VectorRecord, ...]:
    emb = embedder()
    meta = emb.embedding_meta()
    return tuple(
        VectorRecord(
            tenant_id=tenant_id,
            collection=VECTOR_COLLECTION,
            record_id=entity.entity_id,
            vector=emb.embed_vector(entity.canonical_name),
            embedding=meta,
            source_snapshot_hash=entity_graph.graph_version,
        )
        for entity in entity_graph.entities
    )


async def _upsert_and_search(
    store: InMemoryVectorStore,
    records: tuple[VectorRecord, ...],
    *,
    tenant_id: str,
    query_vector: tuple[float, ...],
    k: int,
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    upserted = await store.upsert(tenant_id, records)
    hits = await store.search(tenant_id, VECTOR_COLLECTION, query_vector, k)
    return upserted, hits


def upsert_and_search_entities(
    entity_graph: EntityGraph, *, tenant_id: str = TENANT_1, k: int = 2
) -> tuple[InMemoryVectorStore, tuple[Any, ...], tuple[Any, ...]]:
    """Build a fresh `InMemoryVectorStore`, upsert every resolved entity's
    embedding, then search for the BRAND entity's own embedding (nearest
    neighbor of itself must be itself, distance 0 — the simplest possible
    real ANN-correctness proof over this chain's own real data, not a
    synthetic/unrelated query vector)."""
    store = InMemoryVectorStore()
    records = entity_vector_records(entity_graph, tenant_id=tenant_id)
    brand_record = next(r for r in records if r.record_id == "entity-w4e2e-brand")

    upserted, hits = asyncio.run(
        _upsert_and_search(
            store, records, tenant_id=tenant_id, query_vector=brand_record.vector, k=k
        )
    )
    return store, upserted, hits


# ---------------------------------------------------------------------------
# Stage 5 — claim-evidence ledger: one claim linked to the resolved brand
# entity, backed by evidence anchored to the normalized citation.
# ---------------------------------------------------------------------------

FRESHNESS_POLICY = EvidenceFreshnessPolicy(max_age_seconds=3600)


def build_claim(entity_graph: EntityGraph, *, tenant_id: str = TENANT_1) -> ExtractedClaim:
    brand_entity_id = next(
        e.entity_id for e in entity_graph.entities if e.entity_type.value == "brand"
    )
    return ExtractedClaim(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        project_id=PROJECT_1,  # type: ignore[arg-type]
        claim_id="claim-w4e2e-0001",
        entity_id=brand_entity_id,
        claim_text="Acme W4E2E offers a documented pricing plan.",
        status="active",  # type: ignore[arg-type]
        effective_from=FIXED_TIMESTAMP,  # type: ignore[arg-type]
        created_at=FIXED_TIMESTAMP,  # type: ignore[arg-type]
    )


def build_evidence(
    citation_result: CitationNormalizationResult, *, tenant_id: str = TENANT_1
) -> EvidenceRecord:
    return EvidenceRecord(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        project_id=PROJECT_1,  # type: ignore[arg-type]
        evidence_id="evidence-w4e2e-0001",
        claim_id="claim-w4e2e-0001",
        source_uri=citation_result.record.normalized_uri,  # type: ignore[arg-type]
        excerpt="Documented pricing plan referenced by the normalized citation.",
        freshness_checked_at=FIXED_TIMESTAMP,  # type: ignore[arg-type]
        content_hash=citation_result.record.content_hash,  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class ClaimEvidenceBuild:
    ledger_state: ClaimEvidenceLedgerState
    link_statuses: dict[str, EvidenceLinkStatus]
    claim: ExtractedClaim
    evidence: EvidenceRecord


def build_claim_evidence_ledger(
    entity_graph: EntityGraph,
    citation_result: CitationNormalizationResult,
    *,
    tenant_id: str = TENANT_1,
) -> ClaimEvidenceBuild:
    claim = build_claim(entity_graph, tenant_id=tenant_id)
    evidence = build_evidence(citation_result, tenant_id=tenant_id)
    link_statuses: dict[str, EvidenceLinkStatus] = {}

    ledger_state: ClaimEvidenceLedgerState = ()
    ledger_state, _ = append_claim(ledger_state, claim)
    ledger_state, _ = append_evidence(
        ledger_state,
        evidence,
        link_statuses=link_statuses,
        now=_parsed_fixed_timestamp(),
        policy=FRESHNESS_POLICY,
    )
    return ClaimEvidenceBuild(
        ledger_state=ledger_state, link_statuses=link_statuses, claim=claim, evidence=evidence
    )


def _parsed_fixed_timestamp():  # noqa: ANN202 - datetime, kept local to avoid an unused top-level import
    from datetime import UTC, datetime

    return datetime(2026, 7, 13, 0, 0, 0, tzinfo=UTC)


def claim_evidence_envelope(
    build: ClaimEvidenceBuild, *, tenant_id: str = TENANT_1
) -> dict[str, Any]:
    # The ledger tail entry's OWN `canonical_hash` (already a `sha256:<hex>`
    # content hash over that entry, computed by `ledger.append_*` itself via
    # `compute_ledger_entry_hash`) IS this snapshot's `ledger_version` — never
    # re-hashed a second, different way here.
    ledger_version = build.ledger_state[-1].canonical_hash
    return build_claim_evidence_versioned_event(
        tenant_id=tenant_id,
        run_id=RUN_ID,
        project_id=PROJECT_1,
        ledger_version=ledger_version,
        ledger_state=build.ledger_state,
        provenance_ref=ledger_version,
        idempotency_key=f"{tenant_id}:{RUN_ID}:{PROJECT_1}:{ledger_version}",
        occurred_at=FIXED_TIMESTAMP,
        trace_id="b" * 32,
    )


# ---------------------------------------------------------------------------
# Stage 6 — QEEG projection: read-only replay over the claim-evidence ledger.
# ---------------------------------------------------------------------------


def replay_qeeg(build: ClaimEvidenceBuild, *, tenant_id: str = TENANT_1) -> QeegProjectionState:
    return build_qeeg_projection(tenant_id, build.ledger_state, link_statuses=build.link_statuses)


# ---------------------------------------------------------------------------
# Stage 7 — experiment registration ledger: REGISTRATION ONLY, no outcome.
# ---------------------------------------------------------------------------


def experiment_registration(
    entity_graph: EntityGraph, *, tenant_id: str = TENANT_1, experiment_id: str = "exp-w4e2e-0001"
) -> ExperimentRegistration:
    return ExperimentRegistration(
        experiment_id=experiment_id,
        tenant_id=tenant_id,
        run_id=RUN_ID,
        arms=(
            ExperimentArm(arm_id="arm-baseline", role="baseline", asset_ref="sha256:" + "a" * 64),
            ExperimentArm(arm_id="arm-treatment", role="treatment", asset_ref="sha256:" + "b" * 64),
        ),
        metric_definitions=(
            MetricDefinition(metric_id="citation_presence", description="cited in response"),
        ),
        query_cluster_ref=entity_graph.graph_version,
        locale="en-US",
        browser_policy="desktop-default",
        repeat_count=5,
        asset_hash="sha256:" + "c" * 64,
        code_version_hash="sha256:" + "d" * 64,
        created_by=ACTOR_ID,
        approved_by="actor-w4e2e-approver-01",
        created_at=FIXED_TIMESTAMP,
    )


def register_experiment(
    ledger_state: LedgerState, registration: ExperimentRegistration
) -> tuple[LedgerState, ExperimentRegistration]:
    return register(ledger_state, registration)


def experiment_registered_envelope(entry: ExperimentRegistration) -> dict[str, Any]:
    """Build the REAL `experiment.registered.v1` envelope via `EnvelopeFactory`
    (producer `experiment-attribution-service` — the AsyncAPI catalog's own
    `expected_producer` for this channel, w4-10; that service's own
    orchestration layer is Wave-4-forbidden/not-yet-built (`services/
    experimentation/experiment-attribution-service` is README-only as of
    this worktree), so this harness builds the envelope directly against the
    REAL `EnvelopeFactory` + the REAL registered ledger entry — never a
    hand-built dict pretending to be a valid envelope). This channel
    REQUIRES `payload.engine_id` (ADR-0013 observation/citation/experiment
    family)."""
    assert entry.canonical_hash is not None
    return EnvelopeFactory.build_tenant_envelope(
        producer="experiment-attribution-service",
        event_type="experiment.registered.v1",
        tenant_id=entry.tenant_id,
        run_id=entry.run_id,
        idempotency_key=f"{entry.tenant_id}:{entry.run_id}:{entry.experiment_id}:registered",
        payload={
            "engine_id": ENGINE_ID,
            "experiment_id": entry.experiment_id,
            "canonical_hash": entry.canonical_hash,
        },
        occurred_at=FIXED_TIMESTAMP,
        trace_id="c" * 32,
    )


def experiment_anchored_envelope(entry: ExperimentRegistration) -> dict[str, Any]:
    """Build the REAL `experiment.anchored.v1` envelope — the audit-anchor
    notification for the SAME registered entry (`previous_hash` carries the
    ledger's own hash-chain anchor, GENESIS-safe: `None` for the first
    entry)."""
    assert entry.canonical_hash is not None
    return EnvelopeFactory.build_tenant_envelope(
        producer="experiment-attribution-service",
        event_type="experiment.anchored.v1",
        tenant_id=entry.tenant_id,
        run_id=entry.run_id,
        idempotency_key=f"{entry.tenant_id}:{entry.run_id}:{entry.experiment_id}:anchored",
        payload={
            "engine_id": ENGINE_ID,
            "experiment_id": entry.experiment_id,
            "canonical_hash": entry.canonical_hash,
            "previous_hash": entry.previous_hash,
        },
        occurred_at=FIXED_TIMESTAMP,
        trace_id="d" * 32,
    )


# ---------------------------------------------------------------------------
# Whole-chain result bundle — used by both the pure-synthetic and the
# ClickHouse-backed lane so their outputs are directly, field-by-field
# comparable.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompositeChainResult:
    graph: DemandGraph
    demand_graph_envelope: dict[str, Any]
    observation_run: PooledObservationRunResult
    citation_results: list[CitationNormalizationResult]
    entity_graph: EntityGraph
    entity_graph_envelope: dict[str, Any]
    vector_upserted: tuple[Any, ...]
    vector_search_hits: tuple[Any, ...]
    claim_evidence_build: ClaimEvidenceBuild
    claim_evidence_envelope: dict[str, Any]
    qeeg_state: QeegProjectionState
    experiment_ledger: LedgerState
    experiment_entry: ExperimentRegistration
    experiment_registered_envelope: dict[str, Any]
    experiment_anchored_envelope: dict[str, Any]


def run_composite_chain(*, tenant_id: str = TENANT_1) -> CompositeChainResult:
    """Run the full demand-graph -> observer -> citation -> entity-resolution
    -> claim-evidence -> QEEG -> experiment-ledger chain once, for
    `tenant_id`, and return every intermediate artifact so a caller can
    assert on each stage individually (never just the final value)."""
    graph = build_graph(tenant_id=tenant_id)
    dg_envelope = demand_graph_envelope(graph)

    observation_run = run_observations(graph, tenant_id=tenant_id)
    citation_results = normalize_observation_citations(observation_run, tenant_id=tenant_id)

    entity_graph = build_entities(graph, tenant_id=tenant_id)
    eg_envelope = entity_graph_envelope(entity_graph)

    _vector_store, vector_upserted, vector_search_hits = upsert_and_search_entities(
        entity_graph, tenant_id=tenant_id
    )

    ce_build = build_claim_evidence_ledger(entity_graph, citation_results[0], tenant_id=tenant_id)
    ce_envelope = claim_evidence_envelope(ce_build, tenant_id=tenant_id)

    qeeg_state = replay_qeeg(ce_build, tenant_id=tenant_id)

    registration = experiment_registration(entity_graph, tenant_id=tenant_id)
    ledger_state, entry = register_experiment((), registration)
    registered_envelope = experiment_registered_envelope(entry)
    anchored_envelope = experiment_anchored_envelope(entry)

    return CompositeChainResult(
        graph=graph,
        demand_graph_envelope=dg_envelope,
        observation_run=observation_run,
        citation_results=citation_results,
        entity_graph=entity_graph,
        entity_graph_envelope=eg_envelope,
        vector_upserted=vector_upserted,
        vector_search_hits=vector_search_hits,
        claim_evidence_build=ce_build,
        claim_evidence_envelope=ce_envelope,
        qeeg_state=qeeg_state,
        experiment_ledger=ledger_state,
        experiment_entry=entry,
        experiment_registered_envelope=registered_envelope,
        experiment_anchored_envelope=anchored_envelope,
    )


__all__ = [
    "ACTOR_ID",
    "COMPETITOR_DOMAINS",
    "ENGINE_ID",
    "FIXED_TIMESTAMP",
    "FRESHNESS_POLICY",
    "OWNED_DOMAINS",
    "PROJECT_1",
    "RUN_ID",
    "TENANT_1",
    "TENANT_2",
    "VECTOR_COLLECTION",
    "ClaimEvidenceBuild",
    "CompositeChainResult",
    "alias_groups",
    "build_claim",
    "build_claim_evidence_ledger",
    "build_entities",
    "build_evidence",
    "build_graph",
    "claim_evidence_envelope",
    "cluster_queries",
    "demand_graph_envelope",
    "embedder",
    "entity_graph_envelope",
    "entity_vector_records",
    "experiment_anchored_envelope",
    "experiment_registered_envelope",
    "experiment_registration",
    "first_party_materials",
    "fixed_clock",
    "fixture_responses",
    "job_context",
    "normalize_observation_citations",
    "register_experiment",
    "replay_qeeg",
    "run_composite_chain",
    "run_observations",
    "upsert_and_search_entities",
    "verify_ledger",
    "verify_ledger_chain",
]
