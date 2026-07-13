"""`build_demand_graph` — deterministic first-party query-cluster (demand
graph) builder.

Pipeline, in order, over the caller-supplied `materials` sequence (already
approved first-party input — see `records.FirstPartyMaterial` docstring):

1. `_classify_intent(material)` — a deterministic keyword classifier over
   `material.text` maps every material to exactly one `records.IntentLabel`
   (Algorithm spec §3.1 Query Cluster `intent` field; taxonomy from the
   demand-agent role description). Raises `UnknownIntentError` for a
   material whose text matches none of the 9 intent keyword sets — this
   package never silently drops or defaults an unlabelled material (mission:
   "근거 없는 수요 추정 금지" / no unsupported demand estimation).
2. Materials are grouped by `(intent, locale)` — one `QueryCluster` per
   group (Algorithm spec: "실제 질문 공간의 canonical node").
3. Each cluster's `paraphrases` and `provenance_refs` are the SORTED,
   deduplicated `text`/`provenance_ref` values of its member materials
   (order-independent of input iteration order — canonical-determinism
   requirement).
4. `business_value` is a deterministic function of member count (more
   corroborating first-party materials => higher confidence signal), never
   a fabricated/estimated external metric (mission: outcome/lift/KPI-weight
   is Wave-5/FORBIDDEN here — this is registration/derivation only over the
   input's own multiplicity, not a causal or outcome claim).
5. `confidence` is `min(1.0, member_count / _CONFIDENCE_SATURATION)` — a
   pure, deterministic function of how many first-party materials corroborate
   the cluster, again never an external/causal estimate.
6. Clusters are sorted by `cluster_id` (itself deterministic — see
   `_cluster_id`) before being placed into `records.DemandGraph.clusters`,
   so cluster ORDER in the output tuple never depends on Python dict/set
   iteration order or input material order.
7. `compute_graph_version` hashes `(tenant_id, project_id, clusters)` via
   `saena_domain.audit.canonical.canonical_json` + `sha256_hex` — reusing
   the shared canonicalization/hashing rule verbatim (mission instruction:
   "do NOT invent a new hashing/canonicalization rule").
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Final

from saena_domain.audit.canonical import canonical_json, sha256_hex

from saena_demand_graph.errors import EmptyMaterialSetError, UnknownIntentError
from saena_demand_graph.records import (
    DemandGraph,
    FirstPartyMaterial,
    FunnelStage,
    IntentLabel,
    QueryCluster,
)

#: Deterministic keyword -> intent map (demand-agent role description's
#: 9-label taxonomy). Every keyword list is lowercase; classification
#: lowercases `material.text` before matching, so this classifier is
#: case-insensitive but otherwise a pure, fixture-free function of the input
#: text (no ML/embedding/external-API call — determinism + offline mission
#: requirement).
_INTENT_KEYWORDS: Final[dict[IntentLabel, tuple[str, ...]]] = {
    IntentLabel.PRICING: ("price", "pricing", "cost", "plan", "quote", "billing"),
    IntentLabel.SECURITY: ("security", "compliance", "soc 2", "gdpr", "encryption", "audit log"),
    IntentLabel.INTEGRATION: ("integrate", "integration", "api", "webhook", "connector", "sync"),
    IntentLabel.COMPARISON: (" vs ", "versus", "compare", "comparison", "alternative"),
    IntentLabel.MIGRATION: ("migrate", "migration", "import data", "switch from", "export"),
    IntentLabel.IMPLEMENTATION: ("setup", "how do i", "configure", "getting started", "install"),
    IntentLabel.SUPPORT: ("error", "not working", "troubleshoot", "issue", "bug", "help"),
    IntentLabel.PROCUREMENT: ("contract", "procurement", "vendor", "rfp", "msa", "purchase order"),
    IntentLabel.DEFINITION: ("what is", "what does", "definition", "meaning", "explain"),
}

#: Deterministic intent -> funnel map (see `records.FunnelStage` docstring —
#: "never independently supplied").
_FUNNEL_FOR_INTENT: Final[dict[IntentLabel, FunnelStage]] = {
    IntentLabel.DEFINITION: FunnelStage.AWARENESS,
    IntentLabel.COMPARISON: FunnelStage.AWARENESS,
    IntentLabel.PRICING: FunnelStage.CONSIDERATION,
    IntentLabel.INTEGRATION: FunnelStage.CONSIDERATION,
    IntentLabel.SECURITY: FunnelStage.CONSIDERATION,
    IntentLabel.PROCUREMENT: FunnelStage.DECISION,
    IntentLabel.IMPLEMENTATION: FunnelStage.DECISION,
    IntentLabel.MIGRATION: FunnelStage.DECISION,
    IntentLabel.SUPPORT: FunnelStage.RETENTION,
}

#: Member count at which `confidence` saturates to 1.0 — a fixed, documented
#: constant (not a learned/estimated parameter), matching this package's
#: registration-only (not causal/optimization) scope.
_CONFIDENCE_SATURATION: Final[int] = 5

#: Fixed per-material business-value increment — deterministic sum, not an
#: external/estimated metric (see module docstring point 4).
_BUSINESS_VALUE_PER_MATERIAL: Final[int] = 10

_CLUSTER_ID_SAFE_LOCALE = re.compile(r"[^a-z0-9]+")


def _classify_intent(material: FirstPartyMaterial) -> IntentLabel:
    lowered = material.text.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return intent
    raise UnknownIntentError(
        f"material {material.material_id!r} text matches no known intent keyword set",
        context={"material_id": material.material_id},
    )


def _cluster_id(intent: IntentLabel, locale: str) -> str:
    """Deterministic cluster identity: `<intent>:<normalized-locale>` — see
    `records.QueryCluster.cluster_id` docstring."""
    normalized_locale = _CLUSTER_ID_SAFE_LOCALE.sub("-", locale.lower()).strip("-")
    return f"{intent.value}:{normalized_locale}"


def _funnel_for_intent(intent: IntentLabel) -> FunnelStage:
    return _FUNNEL_FOR_INTENT[intent]


def _build_cluster(
    *, intent: IntentLabel, locale: str, members: Sequence[FirstPartyMaterial]
) -> QueryCluster:
    paraphrases = tuple(sorted({m.text for m in members}))
    provenance_refs = tuple(sorted({m.provenance_ref for m in members}))
    member_count = len(members)
    confidence = min(1.0, member_count / _CONFIDENCE_SATURATION)
    return QueryCluster(
        cluster_id=_cluster_id(intent, locale),
        intent=intent,
        funnel=_funnel_for_intent(intent),
        locale=locale,
        business_value=member_count * _BUSINESS_VALUE_PER_MATERIAL,
        paraphrases=paraphrases,
        provenance_refs=provenance_refs,
        confidence=confidence,
    )


def compute_graph_version(
    *, tenant_id: str, project_id: str, clusters: Sequence[QueryCluster]
) -> str:
    """Canonical `sha256:<64-hex>` digest over `(tenant_id, project_id,
    clusters)` — reuses `saena_domain.audit.canonical` verbatim (mission:
    "do NOT invent a new hashing/canonicalization rule"). `clusters` must
    already be in a deterministic (sorted) order — this function does not
    itself sort, so a caller-supplied unsorted sequence would break
    determinism; `build_demand_graph` is the only intended caller and always
    passes the sorted-by-`cluster_id` result.
    """
    material: Mapping[str, object] = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "intent": c.intent.value,
                "funnel": c.funnel.value,
                "locale": c.locale,
                "business_value": c.business_value,
                "paraphrases": list(c.paraphrases),
                "provenance_refs": list(c.provenance_refs),
                "confidence": c.confidence,
            }
            for c in clusters
        ],
    }
    digest = sha256_hex(canonical_json(material))
    return f"sha256:{digest}"


def compute_provenance_ref(materials: Sequence[FirstPartyMaterial]) -> str:
    """Canonical `sha256:<64-hex>` content-addressed provenance anchor for a
    build's input material set — the graph BUILD's own provenance hash
    (contract: `demand.graph.versioned.v1` payload `provenance_ref`,
    `common/identifiers/v1#/$defs/sha256_ref`, "content-addressed hash
    anchoring the graph version's build provenance, mirrors
    repo-intaken.content_hash").

    Digests the SORTED, deduplicated set of member `provenance_ref` URIs
    (never the materials' raw `text`, keeping this anchor stable even if a
    later patch unit adds free-text normalization) — reuses
    `saena_domain.audit.canonical` verbatim, same as `compute_graph_version`.
    """
    refs = sorted({m.provenance_ref for m in materials})
    digest = sha256_hex(canonical_json({"source_provenance_refs": refs}))
    return f"sha256:{digest}"


def build_demand_graph(
    *,
    tenant_id: str,
    project_id: str,
    materials: Sequence[FirstPartyMaterial],
) -> DemandGraph:
    """Build a canonical `DemandGraph` from approved first-party `materials`.

    Raises `EmptyMaterialSetError` if `materials` is empty and
    `UnknownIntentError` (propagated from `_classify_intent`) if any material
    cannot be intent-classified. The returned `DemandGraph.provenance_ref` is
    always `compute_provenance_ref(materials)` — deterministically derived
    from the build's own input, never caller-supplied, so it can never drift
    out of sync with what was actually built (mirrors `graph_version`'s own
    derive-don't-inject discipline).

    Deterministic: identical `(tenant_id, project_id, materials)` always
    produces a byte-identical `DemandGraph.graph_version` AND
    `DemandGraph.provenance_ref` — no wall-clock, random, or external-API
    input is consulted anywhere in this function.
    """
    if not materials:
        raise EmptyMaterialSetError(
            "build_demand_graph requires at least one approved first-party material",
            context={"tenant_id": tenant_id, "project_id": project_id},
        )

    groups: dict[tuple[IntentLabel, str], list[FirstPartyMaterial]] = defaultdict(list)
    for material in materials:
        intent = _classify_intent(material)
        groups[(intent, material.locale)].append(material)

    clusters = sorted(
        (
            _build_cluster(intent=intent, locale=locale, members=members)
            for (intent, locale), members in groups.items()
        ),
        key=lambda c: c.cluster_id,
    )
    clusters_tuple = tuple(clusters)

    graph_version = compute_graph_version(
        tenant_id=tenant_id, project_id=project_id, clusters=clusters_tuple
    )
    provenance_ref = compute_provenance_ref(materials)

    return DemandGraph(
        tenant_id=tenant_id,
        project_id=project_id,
        graph_version=graph_version,
        clusters=clusters_tuple,
        provenance_ref=provenance_ref,
    )


__all__ = ["build_demand_graph", "compute_graph_version", "compute_provenance_ref"]
