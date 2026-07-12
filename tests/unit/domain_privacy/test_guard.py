"""Unit tests for saena_domain.privacy.guard.guard_aggregate_publish (ADR-0013 W2A).

Uses the fixtures under tests/contract/fixtures/envelope/ as source data —
those fixtures are the ADR-0013-mandated permanent regression corpus for the
bypass this gate closes (cohort-below-threshold.json in particular), so the
domain-level unit tests are written directly against them rather than
re-deriving equivalent literals.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from saena_domain.privacy.guard import (
    ForbiddenIdentifierPresentError,
    NotPublishableError,
    SuppressedEventError,
    guard_aggregate_publish,
)
from saena_schemas.envelope.event_envelope_v1 import (
    AggregateContextEnvelope,
    DeIdentificationStatus,
)

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "contract" / "fixtures" / "envelope"


def _load_fixture(*parts: str) -> dict[str, Any]:
    with (FIXTURES_DIR.joinpath(*parts)).open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    # Fixture files carry documentation-only keys prefixed with "_" that are
    # not part of the envelope shape itself (see cohort-below-threshold.json,
    # aggregate-with-tenant-id.json). Strip them before handing the dict to
    # the guard, which only knows the real envelope fields.
    return {k: v for k, v in data.items() if not k.startswith("_")}


@pytest.fixture
def valid_aggregate_envelope() -> dict[str, Any]:
    return _load_fixture("valid", "aggregate-strategy-card-eligible-v1.json")


def test_valid_k_anonymized_aggregate_envelope_publishable(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    guard_aggregate_publish(valid_aggregate_envelope)  # must not raise


def test_valid_envelope_as_generated_pydantic_model_publishable(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    model = AggregateContextEnvelope.model_validate(valid_aggregate_envelope)

    guard_aggregate_publish(model)  # must not raise


def test_cohort_below_threshold_with_k_anonymized_status_rejected() -> None:
    """ADR-0013 permanent regression fixture: cohort_size < privacy_threshold
    with de_identification_status already claiming k_anonymized. Schema alone
    passes this (documented in the fixture's _expected_violation) — the
    runtime gate is the only thing that can catch it, and must.
    """
    data = _load_fixture("invalid", "cohort-below-threshold.json")
    assert data["de_identification_status"] == "k_anonymized"
    assert data["cohort_size"] < data["privacy_threshold"]

    with pytest.raises(SuppressedEventError):
        guard_aggregate_publish(data)


def test_cohort_equal_to_threshold_boundary_passes(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    data["cohort_size"] = data["privacy_threshold"]

    guard_aggregate_publish(data)  # must not raise


def test_missing_privacy_threshold_rejected(valid_aggregate_envelope: dict[str, Any]) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    del data["privacy_threshold"]

    with pytest.raises(ValueError, match="privacy_threshold"):
        guard_aggregate_publish(data)


def test_huge_privacy_threshold_rejected(valid_aggregate_envelope: dict[str, Any]) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    data["privacy_threshold"] = 1_000_000

    with pytest.raises(SuppressedEventError):
        guard_aggregate_publish(data)


def test_suppressed_status_never_publishable_even_if_gate_would_pass(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    assert data["cohort_size"] >= data["privacy_threshold"]  # gate would pass
    data["de_identification_status"] = DeIdentificationStatus.suppressed.value

    with pytest.raises(SuppressedEventError):
        guard_aggregate_publish(data)


def test_pending_review_status_not_publishable(valid_aggregate_envelope: dict[str, Any]) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    data["de_identification_status"] = DeIdentificationStatus.pending_review.value

    with pytest.raises(NotPublishableError):
        guard_aggregate_publish(data)


def test_tenant_id_structurally_present_rejected(valid_aggregate_envelope: dict[str, Any]) -> None:
    """ADR-0013 fixture: aggregate-with-tenant-id.json — forbidden outright."""
    data = _load_fixture("invalid", "aggregate-with-tenant-id.json")
    assert "tenant_id" in data

    with pytest.raises(ForbiddenIdentifierPresentError):
        guard_aggregate_publish(data)


def test_run_id_structurally_present_rejected(valid_aggregate_envelope: dict[str, Any]) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    data["run_id"] = "run-2026-0712-0007"

    with pytest.raises(ForbiddenIdentifierPresentError):
        guard_aggregate_publish(data)


def test_tenant_id_present_but_none_still_rejected(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    """Presence of the key is the violation, independent of its value."""
    data = copy.deepcopy(valid_aggregate_envelope)
    data["tenant_id"] = None

    with pytest.raises(ForbiddenIdentifierPresentError):
        guard_aggregate_publish(data)


def test_missing_lineage_audit_ref_rejected(valid_aggregate_envelope: dict[str, Any]) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    del data["lineage_audit_ref"]

    with pytest.raises(ValueError, match="lineage_audit_ref"):
        guard_aggregate_publish(data)


def test_empty_lineage_audit_ref_rejected(valid_aggregate_envelope: dict[str, Any]) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    data["lineage_audit_ref"] = ""

    with pytest.raises(ValueError, match="lineage_audit_ref"):
        guard_aggregate_publish(data)


def test_lineage_audit_ref_treated_as_opaque_string(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    """Guard must not parse/interpret lineage_audit_ref — any non-empty
    string structurally satisfies the precondition, format is out of scope
    here (ADR-0013:73 hash format left OPEN, application-layer opaque)."""
    data = copy.deepcopy(valid_aggregate_envelope)
    data["lineage_audit_ref"] = "not-a-sha256-but-still-opaque"

    guard_aggregate_publish(data)  # must not raise


def test_wrong_type_input_rejected() -> None:
    with pytest.raises(TypeError):
        guard_aggregate_publish("not-an-envelope")  # type: ignore[arg-type]


def test_missing_cohort_size_rejected(valid_aggregate_envelope: dict[str, Any]) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    del data["cohort_size"]

    with pytest.raises(ValueError, match="cohort_size"):
        guard_aggregate_publish(data)


def test_missing_de_identification_status_rejected(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    del data["de_identification_status"]

    with pytest.raises(ValueError, match="de_identification_status"):
        guard_aggregate_publish(data)


def test_unknown_de_identification_status_rejected(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    data["de_identification_status"] = "anonymized"  # not a valid enum value

    with pytest.raises(ValueError, match="unknown de_identification_status"):
        guard_aggregate_publish(data)


def test_non_str_non_enum_de_identification_status_rejected(
    valid_aggregate_envelope: dict[str, Any],
) -> None:
    data = copy.deepcopy(valid_aggregate_envelope)
    data["de_identification_status"] = 42  # neither str nor DeIdentificationStatus

    with pytest.raises(TypeError, match="de_identification_status"):
        guard_aggregate_publish(data)
