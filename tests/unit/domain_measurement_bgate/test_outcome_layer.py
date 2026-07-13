"""OutcomeLayer closed-enum discipline (H4)."""

from __future__ import annotations

import pytest
from saena_domain.measurement.outcome_layer import OutcomeLayer


def test_members_are_exactly_the_five_closed_layers() -> None:
    assert {layer.value for layer in OutcomeLayer} == {
        "discovery",
        "citation",
        "absorption",
        "prominence",
        "referral",
    }


def test_conversion_is_not_a_member() -> None:
    # conversion/attribution is FORBIDDEN as a B-layer success metric
    # (Algorithm §4:212 / k3s §12:553). It must not be constructable.
    assert "conversion" not in {layer.value for layer in OutcomeLayer}
    with pytest.raises(ValueError):
        OutcomeLayer("conversion")


def test_str_enum_compares_equal_to_wire_value() -> None:
    assert OutcomeLayer.CITATION == "citation"
    assert OutcomeLayer.ABSORPTION.value == "absorption"


def test_absorption_is_data_value_only() -> None:
    # absorption is a valid enum label (data-model support) even though the
    # absorption-analysis P1 model stays off — the enum still admits it.
    assert OutcomeLayer("absorption") is OutcomeLayer.ABSORPTION
