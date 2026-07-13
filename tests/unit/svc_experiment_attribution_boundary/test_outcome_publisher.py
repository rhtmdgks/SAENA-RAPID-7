"""Tests for `saena_experiment_attribution.boundary.outcome_publisher`."""

from __future__ import annotations

import math

import pytest
from factories import (
    TENANT_A,
    FakeManifestLookup,
    make_evidence_manifest,
    make_grs_policy,
    make_passing_b_gate_decision,
    make_single_layer_decision,
    make_window,
)
from saena_domain.measurement.b_gate import BGateDecision, BVerdict, PolicyProvenance
from saena_domain.measurement.did import DiDPolicy, SignalSeries, compute_did
from saena_experiment_attribution.boundary.errors import (
    EngineNotPermittedError,
    PayloadValidationError,
    PublishRefusedError,
)
from saena_experiment_attribution.boundary.outcome_publisher import OutcomePublisher


def _did_result_for(decision: BGateDecision):
    """A minimal DiDResult whose signals line up with the decision's
    qualifying layers (evidence_basis_id/layer values only need to be
    *some* signal series for payload-assembly purposes)."""
    policy = DiDPolicy(min_repeats=1, effect_threshold=0.0, provenance="test_fixture")
    series = tuple(
        SignalSeries(
            layer=layer.value,
            metric_id=f"metric-{i}",
            evidence_basis_id=f"sha256:{i:064d}",
        )
        for i, layer in enumerate(
            decision.qualifying_layers or decision.control_adjusted_view or ["citation"]
        )
    )
    if not series:
        series = (
            SignalSeries(
                layer="citation", metric_id="metric-0", evidence_basis_id="sha256:" + "0" * 64
            ),
        )
    return compute_did(series, policy)


def _publisher_with_verified_manifest(*, tenant_id: str = TENANT_A):
    manifest_lookup = FakeManifestLookup()
    manifest = make_evidence_manifest(tenant_id=tenant_id)
    manifest_lookup.put(tenant_id, manifest)
    publisher = OutcomePublisher(manifest_lookup=manifest_lookup)
    return publisher, manifest_lookup, manifest


def _base_kwargs(*, decision, manifest_hash, engine_id="chatgpt-search"):
    did_result = _did_result_for(decision)
    return dict(
        tenant_id=TENANT_A,
        engine_id=engine_id,
        experiment_id="exp-001",
        registration_canonical_hash="sha256:" + "a" * 64,
        deployment_confirmation_ref="deploy-001",
        window=make_window(),
        did_result=did_result,
        decision=decision,
        manifest_hash=manifest_hash,
        artifact_ref="https://example.com/bundle",
        grs_policy=make_grs_policy(),
    )


def test_pass_verdict_with_all_conditions_met_publishes():
    decision = make_passing_b_gate_decision()
    publisher, _lookup, manifest = _publisher_with_verified_manifest()

    payload = publisher.publish(
        **_base_kwargs(decision=decision, manifest_hash=manifest.manifest_hash)
    )

    assert payload["b_verdict"] == "pass"
    assert payload["engine_id"] == "chatgpt-search"


def test_fail_verdict_publishes_without_policy_gate():
    decision = make_single_layer_decision()
    assert decision.verdict is BVerdict.FAIL
    publisher, _lookup, manifest = _publisher_with_verified_manifest()

    payload = publisher.publish(
        **_base_kwargs(decision=decision, manifest_hash=manifest.manifest_hash)
    )

    assert payload["b_verdict"] == "fail"


def test_publisher_refuses_single_layer_pass():
    """A forged decision claims PASS but only has 1 qualifying layer --
    re-derived independently of the verdict field itself."""
    decision = make_single_layer_decision()
    forged = decision.model_copy(update={"verdict": BVerdict.PASS})
    publisher, _lookup, manifest = _publisher_with_verified_manifest()

    with pytest.raises(PublishRefusedError) as excinfo:
        publisher.publish(**_base_kwargs(decision=forged, manifest_hash=manifest.manifest_hash))

    assert "insufficient_qualifying_layers" in excinfo.value.context["reasons"]


def test_publisher_refuses_unresolved_manifest():
    decision = make_passing_b_gate_decision()
    publisher, _lookup, _manifest = _publisher_with_verified_manifest()
    unknown_hash = "sha256:" + "9" * 64

    with pytest.raises(PublishRefusedError) as excinfo:
        publisher.publish(**_base_kwargs(decision=decision, manifest_hash=unknown_hash))

    assert "evidence_manifest_unresolved" in excinfo.value.context["reasons"]


def test_publisher_refuses_tampered_unverified_manifest():
    decision = make_passing_b_gate_decision()
    manifest_lookup = FakeManifestLookup()
    manifest = make_evidence_manifest(tenant_id=TENANT_A)
    # Force-mutate the sealed manifest so verify_manifest reports tampered
    # (mirrors evidence.py's own "force-mutated object" fail-closed test
    # shape -- object.__setattr__ bypasses the frozen model).
    object.__setattr__(manifest, "manifest_hash", "sha256:" + "f" * 64)
    manifest_lookup.put(TENANT_A, manifest)
    publisher = OutcomePublisher(manifest_lookup=manifest_lookup)

    with pytest.raises(PublishRefusedError) as excinfo:
        publisher.publish(**_base_kwargs(decision=decision, manifest_hash=manifest.manifest_hash))

    assert "evidence_manifest_unverified" in excinfo.value.context["reasons"]


def test_publisher_refuses_non_finite_values_via_model_construct():
    """A decision constructed via model_construct bypasses pydantic's
    allow_inf_nan=False guard entirely -- the BOUNDARY itself must still
    refuse a PASS built on top of it (the schema/model cannot save us)."""
    decision = make_passing_b_gate_decision()
    forged = BGateDecision.model_construct(
        verdict=BVerdict.PASS,
        reason_codes=(),
        raw_view=decision.raw_view,
        control_adjusted_view=decision.control_adjusted_view,
        qualifying_layers=(),  # non-finite forgery also strips qualifying layers
        confidence=math.nan,
        policy_version=decision.policy_version,
        policy_hash=decision.policy_hash,
        policy_provenance=decision.policy_provenance,
        is_production=decision.is_production,
    )
    publisher, _lookup, manifest = _publisher_with_verified_manifest()

    with pytest.raises(PublishRefusedError) as excinfo:
        publisher.publish(**_base_kwargs(decision=forged, manifest_hash=manifest.manifest_hash))

    assert "insufficient_qualifying_layers" in excinfo.value.context["reasons"]


def test_publisher_refuses_inconsistent_provenance_forgery():
    """model_construct can set is_production=True while policy_provenance
    stays TEST_FIXTURE (or vice versa) -- an internally-inconsistent forged
    decision. The publisher must refuse, not trust either field alone."""
    decision = make_passing_b_gate_decision()
    forged = decision.model_copy(update={"is_production": True})
    assert forged.policy_provenance is PolicyProvenance.TEST_FIXTURE
    publisher, _lookup, manifest = _publisher_with_verified_manifest()

    with pytest.raises(PublishRefusedError) as excinfo:
        publisher.publish(**_base_kwargs(decision=forged, manifest_hash=manifest.manifest_hash))

    assert "policy_provenance_not_production_or_test" in excinfo.value.context["reasons"]


def test_engine_id_guard_rejects_non_chatgpt_search():
    decision = make_single_layer_decision()
    publisher, _lookup, manifest = _publisher_with_verified_manifest()

    with pytest.raises(EngineNotPermittedError):
        publisher.publish(
            **_base_kwargs(
                decision=decision,
                manifest_hash=manifest.manifest_hash,
                engine_id="google-ai-overviews",
            )
        )


def test_engine_id_guard_checked_before_policy_gate():
    """Even a PASS decision with a bad engine_id is rejected via the engine
    guard (not accidentally allowed through because the policy gate hasn't
    run yet, and not a confusing double-error)."""
    decision = make_passing_b_gate_decision()
    publisher, _lookup, manifest = _publisher_with_verified_manifest()

    with pytest.raises(EngineNotPermittedError):
        publisher.publish(
            **_base_kwargs(
                decision=decision, manifest_hash=manifest.manifest_hash, engine_id="gemini"
            )
        )


def test_multiple_unmet_reasons_all_collected():
    decision = make_single_layer_decision()
    forged = decision.model_copy(update={"verdict": BVerdict.PASS})
    publisher, _lookup, _manifest = _publisher_with_verified_manifest()
    unknown_hash = "sha256:" + "9" * 64

    with pytest.raises(PublishRefusedError) as excinfo:
        publisher.publish(**_base_kwargs(decision=forged, manifest_hash=unknown_hash))

    reasons = excinfo.value.context["reasons"]
    assert "insufficient_qualifying_layers" in reasons
    assert "evidence_manifest_unresolved" in reasons


def test_revalidation_failure_surfaces_as_payload_validation_error(monkeypatch):
    """Defensive double-check: if the assembled payload somehow fails
    re-validation against its own contract (e.g. a future field/constraint
    change this boundary hasn't caught up with), `_revalidate` must refuse
    to return it rather than silently pass through a payload that does not
    conform. Exercised here by monkeypatching model_validate to simulate
    that failure deterministically."""
    from saena_schemas.event.experiment_outcome_observed_v1 import (
        ExperimentOutcomeObservedV1Payload,
    )

    decision = make_single_layer_decision()
    publisher, _lookup, manifest = _publisher_with_verified_manifest()

    def _always_fail(cls, *args, **kwargs):  # noqa: ARG001
        from pydantic import ValidationError

        raise ValidationError.from_exception_data("ExperimentOutcomeObservedV1Payload", [])

    monkeypatch.setattr(
        ExperimentOutcomeObservedV1Payload, "model_validate", classmethod(_always_fail)
    )

    with pytest.raises(PayloadValidationError):
        publisher.publish(**_base_kwargs(decision=decision, manifest_hash=manifest.manifest_hash))
