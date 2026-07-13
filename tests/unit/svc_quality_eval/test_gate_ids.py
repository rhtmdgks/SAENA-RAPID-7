"""`gate_ids.GateId` closed-vocabulary sanity checks."""

from __future__ import annotations

from saena_quality_eval.gate_ids import (
    ADDITIONAL_GATE_IDS,
    ALGORITHM_11_1_GATE_IDS,
    ALL_GATE_IDS,
    GateId,
)


def test_algorithm_11_1_gate_ids_has_exactly_10_members() -> None:
    assert len(ALGORITHM_11_1_GATE_IDS) == 10


def test_algorithm_11_1_gate_ids_matches_the_spec_table() -> None:
    assert {
        GateId.BUILD,
        GateId.TESTS,
        GateId.LINK_ROUTE,
        GateId.CRAWLABILITY,
        GateId.STRUCTURED_DATA,
        GateId.CONTENT_FIDELITY,
        GateId.SECURITY,
        GateId.ACCESSIBILITY,
        GateId.PERFORMANCE,
        GateId.DIFF_RATIONALITY,
    } == ALGORITHM_11_1_GATE_IDS


def test_every_gate_id_member_is_classified() -> None:
    assert frozenset(GateId) == ALL_GATE_IDS
    assert not (ALGORITHM_11_1_GATE_IDS & ADDITIONAL_GATE_IDS)


def test_gate_id_is_a_str_subclass_for_verbatim_serialization() -> None:
    assert str(GateId.BUILD) == "build"
    assert isinstance(GateId.BUILD, str)
