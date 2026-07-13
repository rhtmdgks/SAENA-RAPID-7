"""`records.py` value-object validation branches."""

from __future__ import annotations

import pytest
from demand_graph_factories import make_material
from saena_demand_graph.errors import MaterialValidationError
from saena_demand_graph.records import (
    DemandGraph,
    FunnelStage,
    IntentLabel,
    MaterialSourceKind,
    QueryCluster,
)


def test_material_valid_construction() -> None:
    material = make_material()
    assert material.material_id == "m1"
    assert material.source_kind == MaterialSourceKind.SALES_TRANSCRIPT


def test_material_empty_material_id_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(material_id="")


def test_material_empty_text_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(text="")


def test_material_text_too_long_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(text="x" * 4097)


def test_material_empty_locale_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(locale="")


def test_material_locale_too_long_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(locale="x" * 17)


def test_material_empty_provenance_ref_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(provenance_ref="")


def test_material_provenance_ref_too_long_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(provenance_ref="doc://" + ("x" * 512))


def test_material_provenance_ref_malformed_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(provenance_ref="not-a-uri")


def test_material_provenance_ref_query_string_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        make_material(provenance_ref="doc://sales/call-1?token=abc")


def test_query_cluster_requires_at_least_one_paraphrase() -> None:
    with pytest.raises(MaterialValidationError):
        QueryCluster(
            cluster_id="pricing:en-us",
            intent=IntentLabel.PRICING,
            funnel=FunnelStage.CONSIDERATION,
            locale="en-US",
            business_value=10,
            paraphrases=(),
            provenance_refs=("doc://a",),
            confidence=0.5,
        )


def test_query_cluster_requires_at_least_one_provenance_ref() -> None:
    with pytest.raises(MaterialValidationError):
        QueryCluster(
            cluster_id="pricing:en-us",
            intent=IntentLabel.PRICING,
            funnel=FunnelStage.CONSIDERATION,
            locale="en-US",
            business_value=10,
            paraphrases=("what is pricing",),
            provenance_refs=(),
            confidence=0.5,
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_query_cluster_confidence_out_of_range_rejected(confidence: float) -> None:
    with pytest.raises(MaterialValidationError):
        QueryCluster(
            cluster_id="pricing:en-us",
            intent=IntentLabel.PRICING,
            funnel=FunnelStage.CONSIDERATION,
            locale="en-US",
            business_value=10,
            paraphrases=("what is pricing",),
            provenance_refs=("doc://a",),
            confidence=confidence,
        )


def test_query_cluster_negative_business_value_rejected() -> None:
    with pytest.raises(MaterialValidationError):
        QueryCluster(
            cluster_id="pricing:en-us",
            intent=IntentLabel.PRICING,
            funnel=FunnelStage.CONSIDERATION,
            locale="en-US",
            business_value=-1,
            paraphrases=("what is pricing",),
            provenance_refs=("doc://a",),
            confidence=0.5,
        )


def test_demand_graph_requires_sha256_provenance_ref() -> None:
    cluster = QueryCluster(
        cluster_id="pricing:en-us",
        intent=IntentLabel.PRICING,
        funnel=FunnelStage.CONSIDERATION,
        locale="en-US",
        business_value=10,
        paraphrases=("what is pricing",),
        provenance_refs=("doc://a",),
        confidence=0.5,
    )
    with pytest.raises(MaterialValidationError):
        DemandGraph(
            tenant_id="acme-inc",
            project_id="proj-1",
            graph_version="sha256:" + ("a" * 64),
            clusters=(cluster,),
            provenance_ref="not-a-sha256-ref",
        )


def test_demand_graph_accepts_well_formed_sha256_provenance_ref() -> None:
    cluster = QueryCluster(
        cluster_id="pricing:en-us",
        intent=IntentLabel.PRICING,
        funnel=FunnelStage.CONSIDERATION,
        locale="en-US",
        business_value=10,
        paraphrases=("what is pricing",),
        provenance_refs=("doc://a",),
        confidence=0.5,
    )
    graph = DemandGraph(
        tenant_id="acme-inc",
        project_id="proj-1",
        graph_version="sha256:" + ("a" * 64),
        clusters=(cluster,),
        provenance_ref="sha256:" + ("b" * 64),
    )
    assert graph.provenance_ref == "sha256:" + ("b" * 64)
