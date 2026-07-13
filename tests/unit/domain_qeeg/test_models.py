"""Unit tests for `saena_domain.qeeg.models`."""

from __future__ import annotations

import dataclasses

import pytest
from qeeg_factories import build_claim_fact, build_evidence_fact
from saena_domain.qeeg.models import (
    ClaimFact,
    EvidenceFact,
    QeegClaimView,
    QeegLinkStatus,
    QeegProjectionState,
)


def test_claim_fact_is_frozen() -> None:
    fact = build_claim_fact()
    with pytest.raises(dataclasses.FrozenInstanceError):
        fact.claim_id = "other"  # type: ignore[misc]


def test_evidence_fact_is_frozen() -> None:
    fact = build_evidence_fact()
    with pytest.raises(dataclasses.FrozenInstanceError):
        fact.evidence_id = "other"  # type: ignore[misc]


def test_qeeg_projection_state_defaults_empty() -> None:
    state = QeegProjectionState(tenant_id="acme-co")
    assert state.claims == ()
    assert state.entity_claims == ()


def test_qeeg_projection_state_is_frozen() -> None:
    state = QeegProjectionState(tenant_id="acme-co")
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.tenant_id = "other"  # type: ignore[misc]


def test_qeeg_link_status_values() -> None:
    assert QeegLinkStatus.LINKED.value == "linked"
    assert QeegLinkStatus.BLOCKED.value == "blocked"


def test_claim_fact_equality_is_structural() -> None:
    a = build_claim_fact()
    b = build_claim_fact()
    assert a == b
    assert a is not b


def test_evidence_fact_equality_is_structural() -> None:
    a = build_evidence_fact()
    b = build_evidence_fact()
    assert a == b
    assert a is not b


def test_qeeg_claim_view_no_pii_fields() -> None:
    # The view carries only identifiers/status/booleans/tuples-of-ids —
    # never free-text claim/evidence content. This test asserts the exact
    # field set so an accidental future addition of a text field is caught.
    field_names = {f.name for f in dataclasses.fields(QeegClaimView)}
    assert field_names == {
        "claim_id",
        "entity_id",
        "status",
        "publishable",
        "blocking_reasons",
        "supporting_evidence_ids",
        "evidence_ids",
    }


def test_claim_fact_no_pii_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(ClaimFact)}
    assert "claim_text" not in field_names


def test_evidence_fact_no_pii_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(EvidenceFact)}
    assert "excerpt" not in field_names
    assert "source_uri" not in field_names
