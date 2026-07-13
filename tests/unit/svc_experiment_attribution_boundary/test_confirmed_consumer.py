"""Tests for `saena_experiment_attribution.boundary.confirmed_consumer`."""

from __future__ import annotations

from datetime import timedelta

import pytest
from factories import (
    EXPERIMENT_ID,
    REGISTRATION_HASH,
    RUN_ID,
    TENANT_A,
    TENANT_B,
    AlwaysTrustVerifier,
    FakeRegistrationLookup,
    FakeWorkflowSignal,
    NeverTrustVerifier,
    make_confirmation_store,
    make_confirmed_payload,
    make_registration_view,
    now,
)
from saena_domain.measurement.confirmation import Accepted, Duplicate, RejectionReason
from saena_experiment_attribution.boundary.confirmed_consumer import (
    DeploymentConfirmedConsumer,
    RejectionRecord,
    TransportMetadata,
)
from saena_experiment_attribution.boundary.errors import (
    PayloadValidationError,
    TenantDuplicationError,
)

_UNSET = object()


def _build_consumer(
    *,
    registration_lookup=None,
    workflow_signal=None,
    confirmation_store=None,
    trust_verifier=_UNSET,
):
    registration_lookup = registration_lookup or FakeRegistrationLookup()
    workflow_signal = workflow_signal or FakeWorkflowSignal()
    confirmation_store = confirmation_store or make_confirmation_store()
    trust_verifier = AlwaysTrustVerifier() if trust_verifier is _UNSET else trust_verifier
    consumer = DeploymentConfirmedConsumer(
        registration_lookup=registration_lookup,
        confirmation_store=confirmation_store,
        workflow_signal=workflow_signal,
        trust_verifier=trust_verifier,
    )
    return consumer, registration_lookup, workflow_signal, confirmation_store


def _transport(*, tenant_id: str = TENANT_A, run_id: str = RUN_ID) -> TransportMetadata:
    return TransportMetadata(
        server_received_at=now(), envelope_tenant_id=tenant_id, envelope_run_id=run_id
    )


def test_happy_path_accept_stores_and_signals():
    consumer, reg_lookup, signal, store = _build_consumer()
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload()

    result = consumer.consume(payload, transport=_transport(), prior_state={})

    assert isinstance(result, Accepted)
    assert signal.calls == [(TENANT_A, EXPERIMENT_ID, result.server_received_at.isoformat())]
    stored = store.get(TENANT_A, result.confirmation.idempotency_key)
    assert stored.tenant_id == TENANT_A


def test_duplicate_confirmation_is_noop_no_double_signal():
    consumer, reg_lookup, signal, store = _build_consumer()
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload()
    prior_state: dict = {}

    first = consumer.consume(payload, transport=_transport(), prior_state=prior_state)
    assert isinstance(first, Accepted)
    prior_state[first.confirmation.idempotency_key] = first
    assert len(signal.calls) == 1

    second = consumer.consume(payload, transport=_transport(), prior_state=prior_state)
    assert isinstance(second, Duplicate)
    assert len(signal.calls) == 1  # no double-signal
    # store not re-written with a conflicting record either (still one entry)
    assert store.get(TENANT_A, first.confirmation.idempotency_key).confirmation_key == (
        first.confirmation.idempotency_key
    )


def test_conflicting_confirmation_rejected_no_raw_payload_echo():
    consumer, reg_lookup, signal, _store = _build_consumer()
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload(confirmer_identity="actor-original")
    prior_state: dict = {}

    first = consumer.consume(payload, transport=_transport(), prior_state=prior_state)
    assert isinstance(first, Accepted)
    prior_state[first.confirmation.idempotency_key] = first

    conflicting_payload = make_confirmed_payload(confirmer_identity="actor-DIFFERENT")
    result = consumer.consume(conflicting_payload, transport=_transport(), prior_state=prior_state)

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.CONFLICTING_REPLAY
    # non-leaking: only typed reason + two identifier refs, nothing else
    dumped = result.model_dump()
    assert set(dumped.keys()) == {"reason_code", "idempotency_key", "experiment_id"}
    assert "actor-DIFFERENT" not in str(dumped)
    assert len(signal.calls) == 1  # rejection never signals


def test_cross_tenant_lookup_returns_absent_oracle_free():
    """Same registration_hash, wrong tenant_id -> absent, not a distinguishing error."""
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(
        make_registration_view(tenant_id=TENANT_A, registration_canonical_hash=REGISTRATION_HASH)
    )

    # Prove the port itself is oracle-free: a real hash under the wrong
    # tenant returns the identical None a nonexistent hash would.
    assert reg_lookup.lookup(TENANT_B, REGISTRATION_HASH) is None
    assert reg_lookup.lookup(TENANT_B, "sha256:" + "0" * 64) is None

    payload = make_confirmed_payload(registration_canonical_hash=REGISTRATION_HASH)
    result = consumer.consume(payload, transport=_transport(tenant_id=TENANT_B), prior_state={})

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.UNKNOWN_REGISTRATION


def test_unknown_registration_hash_same_reason_as_cross_tenant():
    """A genuinely unknown hash under the caller's OWN tenant produces the
    SAME reason code as a cross-tenant real-hash guess — no distinguishing
    signal between the two cases."""
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(
        make_registration_view(tenant_id=TENANT_A, registration_canonical_hash=REGISTRATION_HASH)
    )

    payload = make_confirmed_payload(registration_canonical_hash="sha256:" + "9" * 64)
    result = consumer.consume(payload, transport=_transport(tenant_id=TENANT_A), prior_state={})

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.UNKNOWN_REGISTRATION


def test_backdated_confirmation_rejected():
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(make_registration_view(created_at=now() - timedelta(days=1), approved_at=now()))
    payload = make_confirmed_payload(confirmed_at="2020-01-01T00:00:00Z")

    result = consumer.consume(payload, transport=_transport(), prior_state={})

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.BACKDATED_CONFIRMATION


def test_future_confirmation_rejected():
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload(confirmed_at="2099-01-01T00:00:00Z")

    result = consumer.consume(payload, transport=_transport(), prior_state={})

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.FUTURE_CONFIRMATION


def test_untrusted_confirmer_rejected_fail_closed():
    consumer, reg_lookup, signal, _store = _build_consumer(trust_verifier=NeverTrustVerifier())
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload()

    result = consumer.consume(payload, transport=_transport(), prior_state={})

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.CONFIRMER_VERIFICATION_FAILED
    assert signal.calls == []


def test_missing_trust_verifier_rejected_fail_closed():
    consumer, reg_lookup, signal, _store = _build_consumer(trust_verifier=None)
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload()

    result = consumer.consume(payload, transport=_transport(), prior_state={})

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.UNTRUSTED_CONFIRMER
    assert signal.calls == []


def test_payload_tenant_duplication_rejected_adr_0014():
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload(extra_tenant_id=TENANT_A)

    with pytest.raises(TenantDuplicationError) as excinfo:
        consumer.consume(payload, transport=_transport(), prior_state={})

    assert excinfo.value.context["field"] == "tenant_id"


def test_payload_run_id_duplication_rejected_adr_0014():
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload()
    payload["run_id"] = RUN_ID

    with pytest.raises(TenantDuplicationError):
        consumer.consume(payload, transport=_transport(), prior_state={})


def test_missing_deploy_artifact_domain_rejected():
    # The generated payload model does not enforce the JSON-Schema-only
    # allOf/anyOf "at least one of deployed_commit_sha/artifact_hash"
    # constraint (datamodel-codegen limitation) -- the domain guard
    # (validate_confirmation's MISSING_DEPLOY_ARTIFACT check) is what
    # actually catches this, fail-closed, one layer down.
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload(deployed_commit_sha=None, artifact_hash=None)

    result = consumer.consume(payload, transport=_transport(), prior_state={})

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.MISSING_DEPLOY_ARTIFACT


def test_malformed_payload_missing_required_field_rejected():
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(make_registration_view())
    payload = make_confirmed_payload()
    del payload["confirmer"]

    with pytest.raises(PayloadValidationError):
        consumer.consume(payload, transport=_transport(), prior_state={})


def test_identity_mismatch_rejected():
    # registration_ref matches the hash lookup, but the registration's own
    # run_id differs from the envelope-supplied run_id (transport) — a
    # non-tenant identity mismatch.
    consumer, reg_lookup, _signal, _store = _build_consumer()
    reg_lookup.put(make_registration_view(run_id="other-run"))
    payload = make_confirmed_payload()

    result = consumer.consume(payload, transport=_transport(run_id=RUN_ID), prior_state={})

    assert isinstance(result, RejectionRecord)
    assert result.reason_code is RejectionReason.IDENTITY_MISMATCH
