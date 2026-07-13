"""`build_claim_evidence_versioned_event` — validity against the real
generated `saena_schemas.event.claim_evidence_versioned_v1` model and the
CONFIRMED v1 AsyncAPI catalog (dual jsonschema + pydantic, via
`EnvelopeFactory`)."""

from __future__ import annotations

import pytest
from claim_evidence_factories import NOW, PROJECT_A, TENANT_A, build_claim, build_evidence
from pydantic import ValidationError
from saena_claim_evidence import (
    EvidenceFreshnessPolicy,
    append_claim,
    append_evidence,
    build_claim_evidence_versioned_event,
    compute_ledger_entry_hash,
)
from saena_claim_evidence.events import EVENT_TYPE, PRODUCER, summarize_ledger
from saena_domain.events import ProducerMismatchError, TopicMismatchError
from saena_schemas.event.claim_evidence_versioned_v1 import ClaimEvidenceVersionedV1Payload

POLICY = EvidenceFreshnessPolicy(max_age_seconds=3600)


def _built_ledger():
    ledger, _ = append_claim((), build_claim())
    ledger, _ = append_evidence(ledger, build_evidence(), link_statuses={}, now=NOW, policy=POLICY)
    return ledger


def test_summarize_ledger_counts_distinct_claims_and_evidence() -> None:
    ledger = _built_ledger()
    claim_count, evidence_count = summarize_ledger(ledger)
    assert claim_count == 1
    assert evidence_count == 1


def test_summarize_ledger_does_not_double_count_reevaluated_claim_entries() -> None:
    """A claim that gets a second, re-evaluated entry appended (see
    ledger.py's fail-closed-on-mutation) must still count once."""
    ledger = _built_ledger()
    # the append_evidence call above already appended a re-evaluated claim
    # entry (publishability flipped from False to True) — 3 total entries,
    # 1 distinct claim.
    assert len(ledger) == 3
    claim_count, _ = summarize_ledger(ledger)
    assert claim_count == 1


def test_build_event_produces_a_dual_valid_envelope() -> None:
    ledger = _built_ledger()
    provenance_ref = compute_ledger_entry_hash({"ledger_version": "v1", "entry_count": len(ledger)})

    envelope = build_claim_evidence_versioned_event(
        tenant_id=TENANT_A,
        run_id="run-0001",
        project_id=PROJECT_A,
        ledger_version="v1",
        ledger_state=ledger,
        provenance_ref=provenance_ref,
        idempotency_key=f"{TENANT_A}:run-0001:v1",
    )

    assert envelope["event_type"] == EVENT_TYPE
    assert envelope["producer"] == PRODUCER
    assert envelope["context_type"] == "tenant"
    assert envelope["tenant_id"] == TENANT_A
    assert envelope["payload"]["claim_count"] == 1
    assert envelope["payload"]["evidence_count"] == 1
    assert envelope["payload"]["provenance_ref"] == provenance_ref

    # Independently re-validate the payload against the REAL generated
    # pydantic model (not just trusting EnvelopeFactory's internal check).
    ClaimEvidenceVersionedV1Payload.model_validate(envelope["payload"])


def test_build_event_payload_has_exactly_the_five_task_fields() -> None:
    ledger = _built_ledger()
    provenance_ref = compute_ledger_entry_hash({"x": 1})
    envelope = build_claim_evidence_versioned_event(
        tenant_id=TENANT_A,
        run_id="run-0001",
        project_id=PROJECT_A,
        ledger_version="v1",
        ledger_state=ledger,
        provenance_ref=provenance_ref,
        idempotency_key="idem-0001",
    )
    assert set(envelope["payload"].keys()) == {
        "project_id",
        "ledger_version",
        "claim_count",
        "evidence_count",
        "provenance_ref",
    }


def test_build_event_never_reprojects_tenant_id_or_run_id_into_payload() -> None:
    ledger = _built_ledger()
    envelope = build_claim_evidence_versioned_event(
        tenant_id=TENANT_A,
        run_id="run-0001",
        project_id=PROJECT_A,
        ledger_version="v1",
        ledger_state=ledger,
        provenance_ref=compute_ledger_entry_hash({"x": 1}),
        idempotency_key="idem-0001",
    )
    assert "tenant_id" not in envelope["payload"]
    assert "run_id" not in envelope["payload"]


def test_a_malformed_provenance_ref_fails_the_real_generated_payload_model() -> None:
    """`claim.evidence.versioned.v1` is not (yet) one of the 6 event_types
    bound into `saena_domain.events.factory.EVENT_PAYLOAD_MODELS`, so
    `EnvelopeFactory`'s own dual validation does not itself reject a
    malformed `provenance_ref` (see that factory's own "Deferred-scope
    note" precedent for the analogous quality-gate-result gap) — the
    channel-payload contract is still enforced independently, directly
    against the REAL generated model, which is what this test pins."""
    ledger = _built_ledger()
    envelope = build_claim_evidence_versioned_event(
        tenant_id=TENANT_A,
        run_id="run-0001",
        project_id=PROJECT_A,
        ledger_version="v1",
        ledger_state=ledger,
        provenance_ref="not-a-sha256-ref",
        idempotency_key="idem-0001",
    )
    with pytest.raises(ValidationError):
        ClaimEvidenceVersionedV1Payload.model_validate(envelope["payload"])


def test_an_empty_ledger_version_fails_the_real_generated_payload_model() -> None:
    ledger = _built_ledger()
    envelope = build_claim_evidence_versioned_event(
        tenant_id=TENANT_A,
        run_id="run-0001",
        project_id=PROJECT_A,
        ledger_version="",
        ledger_state=ledger,
        provenance_ref=compute_ledger_entry_hash({"x": 1}),
        idempotency_key="idem-0001",
    )
    with pytest.raises(ValidationError):
        ClaimEvidenceVersionedV1Payload.model_validate(envelope["payload"])


def test_event_type_matches_the_confirmed_asyncapi_channel() -> None:
    assert EVENT_TYPE == "claim.evidence.versioned.v1"


def test_wrong_producer_is_rejected_by_the_asyncapi_catalog() -> None:
    """Defence-in-depth check: `EnvelopeFactory` itself (not this module)
    is what enforces the producer==claim-evidence-service binding — proven
    here directly against the real catalog to pin the expectation."""
    from saena_domain.events import EnvelopeFactory

    with pytest.raises(ProducerMismatchError):
        EnvelopeFactory.build_tenant_envelope(
            producer="some-other-service",
            event_type=EVENT_TYPE,
            tenant_id=TENANT_A,
            run_id="run-0001",
            idempotency_key="idem-0001",
            payload={
                "project_id": PROJECT_A,
                "ledger_version": "v1",
                "claim_count": 0,
                "evidence_count": 0,
                "provenance_ref": compute_ledger_entry_hash({"x": 1}),
            },
        )


def test_unknown_event_type_is_rejected() -> None:
    from saena_domain.events import EnvelopeFactory

    with pytest.raises(TopicMismatchError):
        EnvelopeFactory.build_tenant_envelope(
            producer=PRODUCER,
            event_type="claim.evidence.not.a.real.topic.v1",
            tenant_id=TENANT_A,
            run_id="run-0001",
            idempotency_key="idem-0001",
            payload={},
        )
