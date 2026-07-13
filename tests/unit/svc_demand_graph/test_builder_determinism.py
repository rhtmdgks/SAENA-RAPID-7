"""Canonical determinism: identical input -> byte-identical `graph_version`
and `provenance_ref`, and stable cluster ordering."""

from __future__ import annotations

import pytest
from demand_graph_factories import make_material, make_materials_for_all_intents
from saena_demand_graph.builder import (
    build_demand_graph,
    compute_graph_version,
    compute_provenance_ref,
)
from saena_demand_graph.errors import EmptyMaterialSetError
from saena_demand_graph.records import MaterialSourceKind


def test_same_input_twice_yields_identical_graph_version() -> None:
    materials = make_materials_for_all_intents()
    graph_1 = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    graph_2 = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    assert graph_1.graph_version == graph_2.graph_version
    assert graph_1.provenance_ref == graph_2.provenance_ref


def test_same_input_different_process_order_still_identical() -> None:
    """Feeding materials in a DIFFERENT list order must not change the
    output hash — canonical determinism must be independent of input
    iteration order, not just repeat-call stable."""
    materials = make_materials_for_all_intents()
    reversed_materials = list(reversed(materials))
    graph_forward = build_demand_graph(
        tenant_id="acme-inc", project_id="proj-1", materials=materials
    )
    graph_reversed = build_demand_graph(
        tenant_id="acme-inc", project_id="proj-1", materials=reversed_materials
    )
    assert graph_forward.graph_version == graph_reversed.graph_version
    assert graph_forward.clusters == graph_reversed.clusters


def test_different_tenant_id_changes_graph_version() -> None:
    materials = make_materials_for_all_intents()
    graph_a = build_demand_graph(tenant_id="tenant-a", project_id="proj-1", materials=materials)
    graph_b = build_demand_graph(tenant_id="tenant-b", project_id="proj-1", materials=materials)
    assert graph_a.graph_version != graph_b.graph_version


def test_different_project_id_changes_graph_version() -> None:
    materials = make_materials_for_all_intents()
    graph_a = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    graph_b = build_demand_graph(tenant_id="acme-inc", project_id="proj-2", materials=materials)
    assert graph_a.graph_version != graph_b.graph_version


def test_different_material_content_changes_graph_version() -> None:
    materials_a = [make_material(text="what is your pricing plan")]
    materials_b = [make_material(text="what is your pricing plan and cost")]
    graph_a = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials_a)
    graph_b = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials_b)
    assert graph_a.graph_version != graph_b.graph_version


def test_clusters_are_sorted_by_cluster_id() -> None:
    materials = make_materials_for_all_intents()
    graph = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    cluster_ids = [c.cluster_id for c in graph.clusters]
    assert cluster_ids == sorted(cluster_ids)


def test_empty_material_set_raises() -> None:
    with pytest.raises(EmptyMaterialSetError):
        build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=[])


def test_compute_graph_version_is_pure_function_of_inputs() -> None:
    materials = make_materials_for_all_intents()
    graph = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    recomputed = compute_graph_version(
        tenant_id="acme-inc", project_id="proj-1", clusters=graph.clusters
    )
    assert recomputed == graph.graph_version


def test_compute_provenance_ref_deduplicates_and_sorts_refs() -> None:
    materials_a = [
        make_material(material_id="m1", provenance_ref="doc://b", text="what is pricing"),
        make_material(material_id="m2", provenance_ref="doc://a", text="what is pricing"),
    ]
    materials_b = [
        make_material(material_id="m3", provenance_ref="doc://a", text="what is pricing"),
        make_material(material_id="m4", provenance_ref="doc://b", text="what is pricing"),
    ]
    ref_a = compute_provenance_ref(materials_a)
    ref_b = compute_provenance_ref(materials_b)
    assert ref_a == ref_b


def test_graph_version_and_provenance_ref_are_well_formed_sha256_refs() -> None:
    materials = make_materials_for_all_intents()
    graph = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    assert graph.graph_version.startswith("sha256:")
    assert len(graph.graph_version) == len("sha256:") + 64
    assert graph.provenance_ref.startswith("sha256:")
    assert len(graph.provenance_ref) == len("sha256:") + 64


def test_multiple_materials_same_intent_locale_form_one_cluster() -> None:
    materials = [
        make_material(material_id="m1", text="what is your pricing plan", locale="en-US"),
        make_material(material_id="m2", text="what is the cost of a plan", locale="en-US"),
    ]
    graph = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    assert len(graph.clusters) == 1
    cluster = graph.clusters[0]
    assert len(cluster.paraphrases) == 2
    assert cluster.business_value == 20


def test_material_source_kind_has_no_external_member() -> None:
    """First-party-only enforcement at the type level (see
    `records.MaterialSourceKind` docstring) — the enum must never grow a
    web_scrape/competitor/third_party member."""
    forbidden = {"web_scrape", "competitor", "third_party", "external"}
    actual = {member.value for member in MaterialSourceKind}
    assert actual.isdisjoint(forbidden)
