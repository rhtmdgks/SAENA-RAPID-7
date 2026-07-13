"""Remaining branch coverage: error `.to_dict()`, cluster-id locale
normalization, package-level re-exports, `records.py` unused-but-defined
`EngineNotPermittedError` shape (no engine-scope check exists inside this
package's own pure builder — see rationale below), and multi-locale
grouping."""

from __future__ import annotations

from demand_graph_factories import make_material
from saena_demand_graph import (
    DemandGraphError,
    EngineNotPermittedError,
    build_demand_graph,
)
from saena_demand_graph.builder import _cluster_id
from saena_demand_graph.records import IntentLabel


def test_demand_graph_error_to_dict_shape() -> None:
    error = DemandGraphError("boom", context={"foo": "bar"})
    rendered = error.to_dict()
    assert rendered["error_code"] == "saena.internal.demand_graph_error"
    assert rendered["message"] == "boom"
    assert rendered["foo"] == "bar"


def test_demand_graph_error_default_context_is_empty_dict() -> None:
    error = DemandGraphError("boom")
    assert error.context == {}
    assert error.to_dict() == {"error_code": "saena.internal.demand_graph_error", "message": "boom"}


def test_engine_not_permitted_error_shape() -> None:
    """`EngineNotPermittedError` is exported for callers that layer an
    engine-scope guard on top of this package's own pure, engine-agnostic
    builder (this package's `build_demand_graph`/`emit_demand_graph_
    versioned_event` never themselves accept or branch on an `engine_id` —
    the CLAUDE.md 'Engine scope (v1)' constraint applies to the OBSERVATION/
    citation layer, not this first-party-material clustering step — but the
    error type is defined here so a future caller-side guard has a single
    canonical exception to raise, consistent with every other `saena_*`
    package's error-hierarchy discipline of defining every domain-relevant
    error up front)."""
    error = EngineNotPermittedError("google-ai-overviews is not permitted")
    assert error.error_code == "saena.policy_denied.engine_not_permitted"
    assert not error.retryable


def test_cluster_id_normalizes_locale_punctuation() -> None:
    assert _cluster_id(IntentLabel.PRICING, "en-US") == "pricing:en-us"
    assert _cluster_id(IntentLabel.PRICING, "en_US") == "pricing:en-us"
    assert _cluster_id(IntentLabel.PRICING, "EN US") == "pricing:en-us"


def test_multi_locale_materials_form_separate_clusters() -> None:
    materials = [
        make_material(material_id="m1", text="what is your pricing plan", locale="en-US"),
        make_material(material_id="m2", text="quel est votre tarif", locale="fr-FR"),
    ]
    # French text won't match the English keyword classifier — use an
    # English-keyword string with a different locale tag instead, since this
    # package's classifier is deliberately keyword-based, not translation-
    # aware (documented scope: no ML/embedding/external-API call).
    materials[1] = make_material(material_id="m2", text="what is your pricing plan", locale="fr-FR")
    graph = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    assert len(graph.clusters) == 2
    locales_seen = {c.locale for c in graph.clusters}
    assert locales_seen == {"en-US", "fr-FR"}


def test_confidence_saturates_at_one() -> None:
    materials = [
        make_material(material_id=f"m{i}", text="what is your pricing plan", locale="en-US")
        for i in range(10)
    ]
    graph = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    assert len(graph.clusters) == 1
    assert graph.clusters[0].confidence == 1.0


def test_package_level_reexports_resolve() -> None:
    import saena_demand_graph as pkg

    assert pkg.build_demand_graph is build_demand_graph
    assert pkg.IntentLabel is IntentLabel
