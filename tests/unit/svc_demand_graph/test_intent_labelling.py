"""Intent labelling: every CONFIRMED intent label reachable, funnel mapping
correctness, and the unknown-intent failure branch."""

from __future__ import annotations

import pytest
from demand_graph_factories import INTENT_SAMPLE_TEXT, make_material, make_materials_for_all_intents
from saena_demand_graph.builder import _classify_intent, _funnel_for_intent
from saena_demand_graph.errors import UnknownIntentError
from saena_demand_graph.records import FunnelStage, IntentLabel


@pytest.mark.parametrize("intent_value", [label.value for label in IntentLabel])
def test_every_intent_label_is_reachable(intent_value: str) -> None:
    text = INTENT_SAMPLE_TEXT[intent_value]
    material = make_material(text=text)
    assert _classify_intent(material) == IntentLabel(intent_value)


def test_every_intent_label_has_a_funnel_mapping() -> None:
    for intent in IntentLabel:
        funnel = _funnel_for_intent(intent)
        assert isinstance(funnel, FunnelStage)


def test_unknown_intent_raises() -> None:
    material = make_material(text="the quick brown fox jumps over the lazy dog")
    with pytest.raises(UnknownIntentError):
        _classify_intent(material)


def test_unknown_intent_propagates_from_build_demand_graph() -> None:
    from saena_demand_graph.builder import build_demand_graph

    material = make_material(text="the quick brown fox jumps over the lazy dog")
    with pytest.raises(UnknownIntentError):
        build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=[material])


def test_classification_is_case_insensitive() -> None:
    material = make_material(text="WHAT IS YOUR PRICING PLAN")
    assert _classify_intent(material) == IntentLabel.PRICING


def test_full_intent_set_produces_one_cluster_per_intent() -> None:
    from saena_demand_graph.builder import build_demand_graph

    materials = make_materials_for_all_intents()
    graph = build_demand_graph(tenant_id="acme-inc", project_id="proj-1", materials=materials)
    intents_seen = {c.intent for c in graph.clusters}
    assert intents_seen == set(IntentLabel)
