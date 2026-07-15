"""Unit tests: saena_domain.events.factory.EnvelopeFactory (ADR-0013 v1).

Covers the task spec's required cases: happy paths x3 contexts, non-Z
timestamp reject, bad trace_id, UUIDv7 format+ordering (see test_uuid7.py),
topic/producer mismatch, google engine reject, payload dup tenant_id reject,
payload schema violation reject, system-context envelope with tenant_id
reject (structural absence). Plus critic SHOULD-FIX 2: engine_id
required-presence for the 3 x-saena-engine-id-required channels.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from saena_domain.events import (
    EngineIdRequiredError,
    EngineNotPermittedError,
    EnvelopeFactory,
    EnvelopeValidationError,
    PayloadDuplicatesEnvelopeFieldError,
    ProducerMismatchError,
    TopicMismatchError,
    is_valid_uuid7,
)
from saena_domain.events._topics import load_topic_catalog
from saena_domain.events._validation import jsonschema_errors
from saena_domain.events.factory import EVENT_PAYLOAD_MODELS
from saena_schemas.envelope.event_envelope_v1 import SaenaEventEnvelopeV1

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_SYSTEM_CHANNEL_ASYNCAPI = _FIXTURES_DIR / "asyncapi_with_system_channel.yaml"


# --------------------------------------------------------------------------
# Happy paths x3 contexts
# --------------------------------------------------------------------------


def test_build_tenant_envelope_happy_path() -> None:
    envelope = EnvelopeFactory.build_tenant_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        tenant_id="acme-co",
        run_id="run-2026-0712-0007",
        idempotency_key="acme-co:run-2026-0712-0007:patch-unit-042",
        payload={
            "patch_unit_id": "w1-04-quality-adrs",
            "worktree_commit": "9f1c2e7",
        },
    )

    assert envelope["context_type"] == "tenant"
    assert envelope["tenant_id"] == "acme-co"
    assert envelope["run_id"] == "run-2026-0712-0007"
    assert is_valid_uuid7(envelope["event_id"])
    assert envelope["occurred_at"].endswith("Z")
    assert len(envelope["trace_id"]) == 32
    # Re-parse with the generated pydantic root model as an independent
    # confirmation the built dict is a genuinely valid envelope instance.
    SaenaEventEnvelopeV1.model_validate(envelope)


def test_build_system_envelope_happy_path() -> None:
    envelope = EnvelopeFactory.build_system_envelope(
        producer="policy-gate",
        event_type="adapter.config.updated.v1",
        idempotency_key="adapter-config:chatgpt-search:v1.3.0",
        payload={"engine_id": "chatgpt-search", "adapter_version": "1.3.0"},
        _asyncapi_path=_SYSTEM_CHANNEL_ASYNCAPI,
    )

    assert envelope["context_type"] == "system"
    assert "tenant_id" not in envelope
    assert "run_id" not in envelope
    SaenaEventEnvelopeV1.model_validate(envelope)


def test_build_aggregate_envelope_happy_path() -> None:
    envelope = EnvelopeFactory.build_aggregate_envelope(
        producer="strategy-skill-bank-service",
        event_type="strategy.card.eligible.v1",
        aggregate_scope_id="aggregate-scope-014",
        cohort_size=12,
        privacy_threshold=5,
        de_identification_status="k_anonymized",
        lineage_audit_ref=(
            "sha256:8f2e1c9a7b3d5f4e6a8c2b1d9f7e3a5c4b6d8f2e1c9a7b3d5f4e6a8c2b1d9f7e"
        ),
        idempotency_key="strategy-card:aggregate-scope-014:2026-07-12",
        payload={
            "card_candidate_ref": "card-cand-0142",
            "source_outcome": {
                "b_verdict": "pass",
                "evidence_bundle_manifest_hash": "sha256:" + "a" * 64,
            },
        },
    )

    assert envelope["context_type"] == "aggregate"
    assert "tenant_id" not in envelope
    assert "run_id" not in envelope
    assert envelope["cohort_size"] == 12
    assert envelope["privacy_threshold"] == 5
    SaenaEventEnvelopeV1.model_validate(envelope)


def test_idempotency_key_is_passed_through_verbatim() -> None:
    envelope = EnvelopeFactory.build_tenant_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        tenant_id="acme-co",
        run_id="run-1",
        idempotency_key="acme-co:run-1:patch-unit-999",
        payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
    )
    assert envelope["idempotency_key"] == "acme-co:run-1:patch-unit-999"


def test_caller_supplied_trace_id_is_preserved() -> None:
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    envelope = EnvelopeFactory.build_tenant_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        tenant_id="acme-co",
        run_id="run-1",
        idempotency_key="k1",
        trace_id=trace_id,
        payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
    )
    assert envelope["trace_id"] == trace_id


def test_empty_payload_is_valid_minimal_value() -> None:
    """ADR-0013 rev.2 (1): payload required in all branches, empty object valid."""
    envelope = EnvelopeFactory.build_system_envelope(
        producer="policy-gate",
        event_type="adapter.config.updated.v1",
        idempotency_key="adapter-config:noop",
        _asyncapi_path=_SYSTEM_CHANNEL_ASYNCAPI,
    )
    assert envelope["payload"] == {}


# --------------------------------------------------------------------------
# occurred_at: non-Z timestamp reject (ADR-0013 rev.2 (2))
# --------------------------------------------------------------------------


def test_occurred_at_offset_form_is_rejected() -> None:
    with pytest.raises(ValueError, match="Z suffix"):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            occurred_at="2026-07-12T09:14:32+00:00",
            payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
        )


def test_occurred_at_without_timezone_is_rejected() -> None:
    with pytest.raises(ValueError, match="Z suffix"):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            occurred_at="2026-07-12T09:14:32",
            payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
        )


# --------------------------------------------------------------------------
# trace_id: bad format reject
# --------------------------------------------------------------------------


def test_bad_trace_id_too_short_is_rejected() -> None:
    with pytest.raises(ValueError, match="32 lowercase-hex"):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            trace_id="abc123",
            payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
        )


def test_bad_trace_id_uppercase_is_rejected() -> None:
    with pytest.raises(ValueError, match="32 lowercase-hex"):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            trace_id="4BF92F3577B34DA6A3CE929D0E0E4736",
            payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
        )


# --------------------------------------------------------------------------
# schema_version: prerelease/build metadata reject (ADR-0013 rev.2 (3))
# --------------------------------------------------------------------------


def test_schema_version_with_prerelease_suffix_is_rejected() -> None:
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            schema_version="1.0.0-rc.1",
            payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
        )


def test_schema_version_with_build_metadata_is_rejected() -> None:
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            schema_version="1.0.0+build.5",
            payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
        )


# --------------------------------------------------------------------------
# Topic/producer discipline
# --------------------------------------------------------------------------


def test_unknown_event_type_raises_topic_mismatch() -> None:
    with pytest.raises(TopicMismatchError):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="not.a.real.topic.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
        )


def test_wrong_producer_for_known_event_type_raises_producer_mismatch() -> None:
    with pytest.raises(ProducerMismatchError):
        EnvelopeFactory.build_tenant_envelope(
            producer="some-other-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
        )


def test_event_type_equals_topic_name_for_all_bound_payload_events() -> None:
    """ADR-0013: event_type value == topic name 1:1 — every CONFIRMED
    payload-bearing event_type must resolve through the real catalog.
    """
    catalog = load_topic_catalog()
    for event_type in EVENT_PAYLOAD_MODELS:
        assert event_type in catalog, f"{event_type} missing from AsyncAPI catalog"


# --------------------------------------------------------------------------
# engine_id guard (Google/Gemini reject)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "engine_id",
    ["google-ai-overviews", "google-ai-mode", "gemini"],
)
def test_non_chatgpt_engine_id_is_rejected(engine_id: str) -> None:
    with pytest.raises(EngineNotPermittedError):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            payload={
                "patch_unit_id": "p",
                "worktree_commit": "9f1c2e7",
                "engine_id": engine_id,
            },
        )


def test_chatgpt_search_engine_id_is_permitted() -> None:
    envelope = EnvelopeFactory.build_system_envelope(
        producer="policy-gate",
        event_type="adapter.config.updated.v1",
        idempotency_key="k1",
        payload={"engine_id": "chatgpt-search"},
        _asyncapi_path=_SYSTEM_CHANNEL_ASYNCAPI,
    )
    assert envelope["payload"]["engine_id"] == "chatgpt-search"


# --------------------------------------------------------------------------
# engine_id required-presence (critic SHOULD-FIX 2, ADR-0013 observation/
# citation/experiment families; x-saena-engine-id-required in the AsyncAPI
# catalog)
# --------------------------------------------------------------------------

# (event_type, expected_producer) for the 3 CONFIRMED v1 channels carrying
# x-saena-engine-id-required: true.
_ENGINE_ID_REQUIRED_CHANNELS = [
    ("observation.captured.v1", "chatgpt-observer-service"),
    ("citation.normalized.v1", "citation-intelligence-service"),
    ("experiment.outcome.observed.v1", "experiment-attribution-service"),
]


@pytest.mark.parametrize(
    ("event_type", "producer"),
    _ENGINE_ID_REQUIRED_CHANNELS,
    ids=[event_type for event_type, _ in _ENGINE_ID_REQUIRED_CHANNELS],
)
def test_engine_id_required_channel_without_engine_id_is_rejected(
    event_type: str, producer: str
) -> None:
    with pytest.raises(EngineIdRequiredError, match=event_type):
        EnvelopeFactory.build_tenant_envelope(
            producer=producer,
            event_type=event_type,
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            payload={},
        )


@pytest.mark.parametrize(
    ("event_type", "producer"),
    _ENGINE_ID_REQUIRED_CHANNELS,
    ids=[event_type for event_type, _ in _ENGINE_ID_REQUIRED_CHANNELS],
)
def test_engine_id_required_channel_with_no_payload_at_all_is_rejected(
    event_type: str, producer: str
) -> None:
    """`payload=None` (factory default -> `{}`) must also trip the
    required-presence guard, not just an explicitly empty dict.
    """
    with pytest.raises(EngineIdRequiredError):
        EnvelopeFactory.build_tenant_envelope(
            producer=producer,
            event_type=event_type,
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
        )


# Minimal schema-valid payloads (beyond just engine_id) for the engine-id
# -required channels that have a BOUND payload model in EVENT_PAYLOAD_MODELS
# (w5-02: experiment.outcome.observed.v1 gained a payload contract, so its
# bound model now requires the full DiD outcome shape, not just engine_id).
# observation.captured.v1 / citation.normalized.v1 are NOT bound to a payload
# model in EVENT_PAYLOAD_MODELS, so their engine_id-only payload still passes
# the factory's model check (which is a no-op for unbound event_types).
_ENGINE_ID_REQUIRED_VALID_PAYLOADS: dict[str, dict] = {
    "observation.captured.v1": {"engine_id": "chatgpt-search"},
    "citation.normalized.v1": {"engine_id": "chatgpt-search"},
    "experiment.outcome.observed.v1": {
        "engine_id": "chatgpt-search",
        "experiment_id": "exp-0001",
        "registration_canonical_hash": "sha256:" + "f" * 64,
        "window": {
            "started_at": "2026-07-07T00:00:00Z",
            "ended_at": "2026-07-14T00:00:00Z",
            "clock_anchor": "deployment_confirmed",
        },
        "deployment_confirmation_ref": "dep-0001",
        "per_signal_results": [
            {
                "outcome_layer": "citation",
                "metric_id": "citation_share",
                "evidence_basis_id": "basis-citation-1",
                "treatment_raw_delta": 0.12,
                "control_raw_delta": 0.02,
                "net_of_control_lift": 0.10,
                "sample_counts": {"treatment": 120, "control": 118},
                "insufficient": False,
            },
        ],
        "b_verdict": "undetermined",
        "raw_view": {},
        "control_adjusted_view": {},
        "confidence": 0.5,
        "evidence_bundle_ref": {
            "manifest_hash": "sha256:" + "a" * 64,
            "artifact_ref": "https://evidence.example.com/bundles/exp-0001",
        },
        "grs_policy": {
            "version": "grs-v1",
            "hash": "sha256:" + "b" * 64,
            "provenance": "test_fixture",
        },
    },
}


@pytest.mark.parametrize(
    ("event_type", "producer"),
    _ENGINE_ID_REQUIRED_CHANNELS,
    ids=[event_type for event_type, _ in _ENGINE_ID_REQUIRED_CHANNELS],
)
def test_engine_id_required_channel_with_chatgpt_search_passes(
    event_type: str, producer: str
) -> None:
    envelope = EnvelopeFactory.build_tenant_envelope(
        producer=producer,
        event_type=event_type,
        tenant_id="acme-co",
        run_id="run-1",
        idempotency_key="k1",
        payload=_ENGINE_ID_REQUIRED_VALID_PAYLOADS[event_type],
    )
    assert envelope["payload"]["engine_id"] == "chatgpt-search"
    SaenaEventEnvelopeV1.model_validate(envelope)


def test_engine_id_required_channel_with_google_engine_is_rejected_as_not_permitted() -> None:
    """Present-but-wrong-value still raises EngineNotPermittedError (not
    EngineIdRequiredError) even on a required-presence channel -- presence
    and value are independent checks.
    """
    with pytest.raises(EngineNotPermittedError):
        EnvelopeFactory.build_tenant_envelope(
            producer="chatgpt-observer-service",
            event_type="observation.captured.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            payload={"engine_id": "gemini"},
        )


def test_engine_id_not_required_on_channels_without_the_asyncapi_flag() -> None:
    """A channel with no x-saena-engine-id-required flag must NOT raise
    EngineIdRequiredError even with an empty payload (regression guard for
    the required-presence check being scoped too broadly).
    """
    envelope = EnvelopeFactory.build_tenant_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        tenant_id="acme-co",
        run_id="run-1",
        idempotency_key="k1",
        payload={"patch_unit_id": "p", "worktree_commit": "9f1c2e7"},
    )
    assert "engine_id" not in envelope["payload"]


# --------------------------------------------------------------------------
# Payload duplicate-identifier reject (ADR-0024(e)-1)
# --------------------------------------------------------------------------


def test_payload_with_tenant_id_key_is_rejected() -> None:
    with pytest.raises(PayloadDuplicatesEnvelopeFieldError):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            payload={
                "patch_unit_id": "p",
                "worktree_commit": "9f1c2e7",
                "tenant_id": "acme-co",
            },
        )


def test_payload_with_run_id_key_is_rejected() -> None:
    with pytest.raises(PayloadDuplicatesEnvelopeFieldError):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            payload={
                "patch_unit_id": "p",
                "worktree_commit": "9f1c2e7",
                "run_id": "run-1",
            },
        )


# --------------------------------------------------------------------------
# Payload schema violation reject (bound generated model)
# --------------------------------------------------------------------------


def test_payload_missing_required_field_is_rejected() -> None:
    with pytest.raises(EnvelopeValidationError):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            # missing required patch_unit_id
            payload={"worktree_commit": "9f1c2e7"},
        )


def test_payload_field_pattern_violation_is_rejected() -> None:
    with pytest.raises(EnvelopeValidationError):
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id="acme-co",
            run_id="run-1",
            idempotency_key="k1",
            payload={"patch_unit_id": "p", "worktree_commit": "not-a-git-sha!"},
        )


def test_aggregate_envelope_dual_validation_rejects_cohort_size_below_minimum() -> None:
    """cohort_size < 1 is not caught by any builder-side field check (only
    the schema-level `minimum: 1` constraint) -- exercises the dual-validate
    path where BOTH jsonschema and pydantic independently reject the same
    envelope (EnvelopeValidationError.messages carries both).
    """
    with pytest.raises(EnvelopeValidationError) as exc_info:
        EnvelopeFactory.build_aggregate_envelope(
            producer="strategy-skill-bank-service",
            event_type="strategy.card.eligible.v1",
            aggregate_scope_id="aggregate-scope-014",
            cohort_size=0,
            privacy_threshold=5,
            de_identification_status="k_anonymized",
            lineage_audit_ref="sha256:" + "0" * 64,
            idempotency_key="k1",
            payload={
                "card_candidate_ref": "card-cand-1",
                "source_outcome": {
                    "b_verdict": "pass",
                    "evidence_bundle_manifest_hash": "sha256:" + "a" * 64,
                },
            },
        )
    assert len(exc_info.value.messages) >= 1
    assert any("pydantic" in message for message in exc_info.value.messages)


# --------------------------------------------------------------------------
# System-context envelope with tenant_id reject (structural absence)
# --------------------------------------------------------------------------


def test_system_envelope_builder_has_no_tenant_id_parameter() -> None:
    """ADR-0013: system branch tenant_id/run_id are structurally forbidden
    (property itself cannot exist) — enforced at the API surface by
    build_system_envelope simply not accepting these kwargs at all.
    """
    with pytest.raises(TypeError):
        EnvelopeFactory.build_system_envelope(  # type: ignore[call-arg]
            producer="policy-gate",
            event_type="adapter.config.updated.v1",
            idempotency_key="k1",
            tenant_id="acme-co",
            _asyncapi_path=_SYSTEM_CHANNEL_ASYNCAPI,
        )


def test_system_envelope_with_tenant_id_smuggled_via_dual_validation_is_rejected() -> None:
    """Even if a caller builds a system-context dict by hand (bypassing the
    factory's kwarg surface) and injects tenant_id, the dual-validation gate
    (jsonschema `not: anyOf required [tenant_id, run_id]` + pydantic
    `extra="forbid"`) must still reject it — the structural-absence rule is
    also enforced at the validation layer, not just the builder API.
    """
    smuggled = {
        "event_id": "018f3a1f-2b1c-7d4a-8e6f-1a2b3c4d5e6f",
        "context_type": "system",
        "tenant_id": "acme-co",
        "schema_version": "1.0.0",
        "producer": "policy-gate",
        "occurred_at": "2026-07-12T10:02:11Z",
        "trace_id": "7d3f1a9c8e2b4f6a0d5c3b1e9f7a2d4c",
        "idempotency_key": "adapter-config:chatgpt-search:v1.3.0",
        "event_type": "adapter.config.updated.v1",
        "payload": {},
    }
    errors = jsonschema_errors(smuggled)
    assert errors, "expected system-context envelope with tenant_id to fail schema validation"

    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, asserting reject only
        SaenaEventEnvelopeV1.model_validate(smuggled)
