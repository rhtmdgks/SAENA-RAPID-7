"""Domain value objects: `FirstPartyMaterial` (input), `IntentLabel`,
`QueryCluster`, `DemandGraph` (output).

Algorithm spec basis (`docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md`
§3.1 "핵심 데이터 객체" / Query Cluster row): "실제 질문 공간의 canonical node"
with required fields "intent, funnel, locale, business value, paraphrases,
confidence". `docs/architecture/wave4-plan.md` NEW-events list additionally
requires this unit to carry a `provenance_ref` per cluster (mirrors
`saena_site_discovery.records.ContentRecordProjection.evidence_ref`'s "opaque
reference only, never inline raw content" discipline — a `FirstPartyMaterial`
NEVER carries a raw customer-source blob inline; only a reference to
where the approved material lives, e.g. `.saena/source-of-truth.md` or a
first-party-content artifact ref).

Every value object here is frozen/immutable — this package's whole output
(`DemandGraph`) is a canonical, deterministic, replayable artifact, never a
mutable working set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from saena_demand_graph.errors import MaterialValidationError

_TEXT_MAX_LENGTH = 4096
_PROVENANCE_REF_MAX_LENGTH = 512
_LOCALE_MAX_LENGTH = 16
# ADR-0024(f) common uri-field pattern (scheme + `://` + no `?`/`#`) reused
# for provenance_ref's shape check — same discipline
# `saena_site_discovery.records.ContentRecordProjection` applies to
# `evidence_ref`, applied here for the same reason: an opaque reference must
# never be a query-string-shaped (e.g. presigned-token) path, and must never
# BE the raw content itself.
_PROVENANCE_REF_PATTERN = re.compile(r"^[a-z0-9+.-]+://[^?#]+$")


class MaterialSourceKind(StrEnum):
    """Where an approved `FirstPartyMaterial` item originated — every value
    here is first-party-only (task mission: "no external/scraped demand
    data"). There is deliberately NO "web_scrape"/"competitor"/"third_party"
    member on this enum — that omission is itself the enforcement of the
    first-party-only constraint at the type level, not just a runtime check.
    """

    SALES_TRANSCRIPT = "sales_transcript"
    SUPPORT_TICKET = "support_ticket"
    SITE_SEARCH_QUERY = "site_search_query"
    SITE_INVENTORY = "site_inventory"
    SOURCE_OF_TRUTH = "source_of_truth"


class IntentLabel(StrEnum):
    """CONFIRMED B2B-SaaS query-cluster intent taxonomy (demand-agent role
    description `.claude/agents/research/demand-agent.md`: "definition,
    integration, security, pricing, comparison, implementation, migration,
    support, procurement intent 라벨" — verbatim 9-label set, reused here
    rather than inventing a new taxonomy)."""

    DEFINITION = "definition"
    INTEGRATION = "integration"
    SECURITY = "security"
    PRICING = "pricing"
    COMPARISON = "comparison"
    IMPLEMENTATION = "implementation"
    MIGRATION = "migration"
    SUPPORT = "support"
    PROCUREMENT = "procurement"


class FunnelStage(StrEnum):
    """Algorithm spec §3.1 Query Cluster required field `funnel`. A
    deterministic function of `IntentLabel` (see `builder._funnel_for_intent`)
    — never independently supplied, so a cluster's funnel stage can never
    drift out of sync with its intent."""

    AWARENESS = "awareness"
    CONSIDERATION = "consideration"
    DECISION = "decision"
    RETENTION = "retention"


@dataclass(frozen=True, slots=True)
class FirstPartyMaterial:
    """One approved first-party input item (sales/support/site-search/site-
    inventory/source-of-truth text) this package clusters into a
    `QueryCluster`. `text` is the material's own approved wording — never
    raw customer PII (mission constraint: "NO PII, secrets, or raw customer
    source"); callers are responsible for supplying already-redacted/
    approved `text`, exactly as `.saena/source-of-truth.md` is described as
    already-approved in the demand-agent role description.

    `provenance_ref` is an OPAQUE reference to where the approved material
    lives (never the material's own raw file content) — see module
    docstring.
    """

    material_id: str
    source_kind: MaterialSourceKind
    text: str
    locale: str
    provenance_ref: str

    def __post_init__(self) -> None:
        if not self.material_id:
            raise MaterialValidationError(
                "material_id must be a non-empty string",
                context={"field": "material_id"},
            )
        if not self.text:
            raise MaterialValidationError(
                "text must be a non-empty string",
                context={"field": "text", "material_id": self.material_id},
            )
        if len(self.text) > _TEXT_MAX_LENGTH:
            raise MaterialValidationError(
                f"text exceeds {_TEXT_MAX_LENGTH} chars",
                context={
                    "field": "text",
                    "material_id": self.material_id,
                    "length": len(self.text),
                },
            )
        if not self.locale:
            raise MaterialValidationError(
                "locale must be a non-empty string",
                context={"field": "locale", "material_id": self.material_id},
            )
        if len(self.locale) > _LOCALE_MAX_LENGTH:
            raise MaterialValidationError(
                f"locale exceeds {_LOCALE_MAX_LENGTH} chars",
                context={"field": "locale", "material_id": self.material_id},
            )
        if not self.provenance_ref:
            raise MaterialValidationError(
                "provenance_ref must be a non-empty opaque reference "
                "(mission: every cluster must carry a provenance reference)",
                context={"field": "provenance_ref", "material_id": self.material_id},
            )
        if len(self.provenance_ref) > _PROVENANCE_REF_MAX_LENGTH:
            raise MaterialValidationError(
                f"provenance_ref exceeds {_PROVENANCE_REF_MAX_LENGTH} chars",
                context={"field": "provenance_ref", "material_id": self.material_id},
            )
        if not _PROVENANCE_REF_PATTERN.match(self.provenance_ref):
            raise MaterialValidationError(
                f"provenance_ref {self.provenance_ref!r} is not a well-formed "
                "opaque reference (scheme required, '?'/'#' forbidden)",
                context={"field": "provenance_ref", "material_id": self.material_id},
            )


@dataclass(frozen=True, slots=True)
class QueryCluster:
    """Canonical query-cluster node (Algorithm spec §3.1 Query Cluster row).

    `cluster_id` is deterministically derived from `intent` + `locale` (see
    `builder._cluster_id`) — never a random/incrementing id, so identical
    input always yields identical cluster identity (canonical-determinism
    mission requirement). `paraphrases` and `provenance_refs` are stored as
    SORTED tuples (never a set or insertion-order list) so their contribution
    to the canonical hash is order-independent of input iteration order.
    """

    cluster_id: str
    intent: IntentLabel
    funnel: FunnelStage
    locale: str
    business_value: int
    paraphrases: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.paraphrases:
            raise MaterialValidationError(
                "a QueryCluster must carry at least one paraphrase",
                context={"field": "paraphrases", "cluster_id": self.cluster_id},
            )
        if not self.provenance_refs:
            raise MaterialValidationError(
                "a QueryCluster must carry at least one provenance_ref "
                "(mission: 'each with an intent label and a provenance reference')",
                context={"field": "provenance_refs", "cluster_id": self.cluster_id},
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise MaterialValidationError(
                f"confidence {self.confidence!r} must be within [0.0, 1.0]",
                context={"field": "confidence", "cluster_id": self.cluster_id},
            )
        if self.business_value < 0:
            raise MaterialValidationError(
                f"business_value {self.business_value!r} must be >= 0",
                context={"field": "business_value", "cluster_id": self.cluster_id},
            )


#: `provenance_ref` wire shape per the CONFIRMED
#: `demand.graph.versioned.v1` payload contract (w4-10,
#: `packages/contracts/json-schema/event/demand-graph-versioned/v1/
#: demand-graph-versioned.schema.json` `$ref`s
#: `common/identifiers/v1#/$defs/sha256_ref`): "content-addressed hash
#: anchoring the graph version's build provenance (sole ledger anchor,
#: mirrors repo-intaken.content_hash)" — a `sha256:<64-hex>` digest, NOT a
#: URI (contrast `FirstPartyMaterial.provenance_ref` /
#: `QueryCluster.provenance_refs`, which ARE opaque URI references to where
#: each source material lives — a distinct, package-internal concept that
#: is deliberately never itself emitted in the event payload, per that same
#: schema's description: "the full query-cluster graph itself is owned/
#: stored by demand-graph-service, not carried here").
_SHA256_REF_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class DemandGraph:
    """The canonical, deterministic demand-graph build output.

    `graph_version` is a `sha256:<64-hex>` canonical hash over
    `(tenant_id, project_id, clusters)` — see `builder.compute_graph_version`
    — computed via `saena_domain.audit.canonical` (no new hashing/
    canonicalization rule invented here, per mission instruction). Identical
    `(tenant_id, project_id, clusters)` input always yields a byte-identical
    `graph_version`.

    `provenance_ref` is the graph BUILD's own content-addressed provenance
    hash (`sha256:<64-hex>`, see `_SHA256_REF_PATTERN` docstring above) — the
    same value this package's `events.build_demand_graph_versioned_payload`
    places into the `demand.graph.versioned.v1` event's `provenance_ref`
    field, so the stored graph and the published event always anchor to an
    identical value.
    """

    tenant_id: str
    project_id: str
    graph_version: str
    clusters: tuple[QueryCluster, ...]
    provenance_ref: str

    def __post_init__(self) -> None:
        if not _SHA256_REF_PATTERN.match(self.provenance_ref):
            raise MaterialValidationError(
                f"provenance_ref {self.provenance_ref!r} must be a "
                "'sha256:<64-hex>' content-addressed reference "
                "(demand.graph.versioned.v1 payload contract)",
                context={
                    "field": "provenance_ref",
                    "tenant_id": self.tenant_id,
                    "project_id": self.project_id,
                },
            )


__all__ = [
    "DemandGraph",
    "FirstPartyMaterial",
    "FunnelStage",
    "IntentLabel",
    "MaterialSourceKind",
    "QueryCluster",
]
