"""Tests for `saena_strategy_skill_bank.intake.IntakeGuard` (w5-16).

Covers: admit happy path; reject-per-gate (b_verdict fail/undetermined
including model_construct forgery, missing/unverifiable manifest, tampered
manifest, tenant-id smuggle, raw-content smuggle); test-fixture →
test-pool-only; the structural API-surface assertion (no
approve/promote/share/learn callable anywhere in the package); and
determinism.
"""

from __future__ import annotations

import pytest
import saena_strategy_skill_bank as ssb
from pydantic import ValidationError
from saena_domain.measurement.b_gate import BVerdict
from saena_domain.measurement.evidence import EvidenceBundleManifest
from saena_strategy_skill_bank.intake import (
    CandidatePool,
    IntakeCandidate,
    IntakeDecisionStatus,
    IntakeGuard,
    IntakeRejectReason,
    SourceOutcomeAssertion,
    SourceOutcomeProvenance,
)
from skill_bank_factories import (
    VALID_SHA_A,
    build_evidence_entry,
    build_manifest,
    build_strategy_card_eligible_payload,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    *,
    b_verdict: BVerdict = BVerdict.PASS,
    provenance: SourceOutcomeProvenance = SourceOutcomeProvenance.PRODUCTION,
    manifest: EvidenceBundleManifest | None = None,
    manifest_hash: str | None = None,
    card_candidate_ref: str = "candidate-0001",
    extra_payload_fields: dict | None = None,
) -> IntakeCandidate:
    sealed = manifest if manifest is not None else build_manifest()
    claimed_hash = manifest_hash if manifest_hash is not None else sealed.manifest_hash
    return IntakeCandidate(
        card_candidate_ref=card_candidate_ref,
        evidence_bundle_manifest_hash=claimed_hash,
        source_outcome=SourceOutcomeAssertion(
            b_verdict=b_verdict,
            provenance=provenance,
            manifest=sealed if manifest_hash is None else manifest,
        ),
        extra_payload_fields=extra_payload_fields or {},
    )


# ---------------------------------------------------------------------------
# Admit happy path
# ---------------------------------------------------------------------------


def test_admit_happy_path_pass_verified_manifest_production() -> None:
    manifest = build_manifest()
    candidate = IntakeCandidate(
        card_candidate_ref="candidate-0001",
        evidence_bundle_manifest_hash=manifest.manifest_hash,
        source_outcome=SourceOutcomeAssertion(
            b_verdict=BVerdict.PASS,
            provenance=SourceOutcomeProvenance.PRODUCTION,
            manifest=manifest,
        ),
    )

    decision = IntakeGuard().evaluate(candidate)

    assert decision.status is IntakeDecisionStatus.ADMIT_AS_CANDIDATE
    assert decision.pool is CandidatePool.PRODUCTION
    assert decision.reject_reasons == ()
    assert decision.card_candidate_ref == "candidate-0001"


def test_admit_happy_path_via_evaluate_payload_wire_shape() -> None:
    manifest = build_manifest()
    payload = build_strategy_card_eligible_payload(
        evidence_bundle_manifest_hash=manifest.manifest_hash,
    )

    decision = IntakeGuard().evaluate_payload(
        payload,
        provenance=SourceOutcomeProvenance.PRODUCTION,
        manifest=manifest,
    )

    assert decision.status is IntakeDecisionStatus.ADMIT_AS_CANDIDATE
    assert decision.pool is CandidatePool.PRODUCTION


# ---------------------------------------------------------------------------
# Reject: b_verdict fail / undetermined (incl. model_construct forgery)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", [BVerdict.FAIL, BVerdict.UNDETERMINED])
def test_reject_not_b_verified_for_fail_and_undetermined(verdict: BVerdict) -> None:
    decision = IntakeGuard().evaluate(_candidate(b_verdict=verdict))

    assert decision.status is IntakeDecisionStatus.REJECT
    assert decision.pool is None
    assert IntakeRejectReason.NOT_B_VERIFIED in decision.reject_reasons


def test_reject_not_b_verified_forged_via_model_construct() -> None:
    """A `SourceOutcomeAssertion` forged via `model_construct` (bypassing
    pydantic validation entirely, e.g. an attacker-controlled deserializer)
    to claim an UNDETERMINED verdict while everything else is PASS-shaped
    must still be rejected — the guard checks the actual enum member, not
    merely "did construction succeed"."""
    manifest = build_manifest()
    forged = SourceOutcomeAssertion.model_construct(
        b_verdict=BVerdict.UNDETERMINED,
        provenance=SourceOutcomeProvenance.PRODUCTION,
        manifest=manifest,
    )
    candidate = IntakeCandidate.model_construct(
        card_candidate_ref="candidate-0001",
        evidence_bundle_manifest_hash=manifest.manifest_hash,
        source_outcome=forged,
        extra_payload_fields={},
    )

    decision = IntakeGuard().evaluate(candidate)

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.NOT_B_VERIFIED in decision.reject_reasons


def test_reject_undetermined_never_admitted_even_with_valid_evidence() -> None:
    """UNDETERMINED/FAIL outcomes must never be queued for later
    auto-admission — a single `evaluate` call is the only decision point,
    and it is REJECT, full stop (directive requirement 3)."""
    decision = IntakeGuard().evaluate(_candidate(b_verdict=BVerdict.UNDETERMINED))
    assert decision.status is IntakeDecisionStatus.REJECT
    assert decision.pool is None


# ---------------------------------------------------------------------------
# Reject: missing / unverifiable manifest
# ---------------------------------------------------------------------------


def test_reject_missing_manifest_is_unverifiable() -> None:
    decision = IntakeGuard().evaluate(_candidate(manifest=None, manifest_hash=VALID_SHA_A))

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.UNVERIFIABLE_EVIDENCE in decision.reject_reasons


def test_reject_bare_hash_no_manifest_supplied_via_wire_payload() -> None:
    payload = build_strategy_card_eligible_payload(evidence_bundle_manifest_hash=VALID_SHA_A)

    decision = IntakeGuard().evaluate_payload(
        payload,
        provenance=SourceOutcomeProvenance.PRODUCTION,
        manifest=None,
    )

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.UNVERIFIABLE_EVIDENCE in decision.reject_reasons


def test_reject_hash_does_not_match_supplied_manifest() -> None:
    """A manifest is supplied and internally verifies, but the CLAIMED hash
    on the candidate does not equal that manifest's own hash — the caller
    supplied the wrong/stale manifest. Fail-closed: unverifiable, not
    silently accepted because *a* valid manifest happened to be attached."""
    manifest = build_manifest()
    other_manifest = build_manifest(entries=(build_evidence_entry(uri="artifact://other"),))
    assert other_manifest.manifest_hash != manifest.manifest_hash

    candidate = IntakeCandidate(
        card_candidate_ref="candidate-0001",
        evidence_bundle_manifest_hash=manifest.manifest_hash,
        source_outcome=SourceOutcomeAssertion(
            b_verdict=BVerdict.PASS,
            provenance=SourceOutcomeProvenance.PRODUCTION,
            manifest=other_manifest,
        ),
    )

    decision = IntakeGuard().evaluate(candidate)

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.UNVERIFIABLE_EVIDENCE in decision.reject_reasons


# ---------------------------------------------------------------------------
# Reject: tampered manifest (verify_manifest fails)
# ---------------------------------------------------------------------------


def test_reject_tampered_manifest_fails_verification() -> None:
    manifest = build_manifest()
    original_hash = manifest.manifest_hash

    candidate = IntakeCandidate(
        card_candidate_ref="candidate-0001",
        evidence_bundle_manifest_hash=original_hash,
        source_outcome=SourceOutcomeAssertion(
            b_verdict=BVerdict.PASS,
            provenance=SourceOutcomeProvenance.PRODUCTION,
            manifest=manifest,
        ),
    )

    # Force-mutate the sealed, frozen manifest ALREADY NESTED inside the
    # constructed candidate (pydantic does not re-run validators on a
    # `object.__setattr__` force-mutation of an already-constructed nested
    # model) to simulate a manifest that was tampered with after sealing —
    # mirrors evidence.py's own "force-mutated object" adversarial precedent.
    nested_manifest = candidate.source_outcome.manifest
    assert nested_manifest is not None
    tampered_commitments = ("sha256:" + "f" * 64,) * len(nested_manifest.entry_commitments)
    object.__setattr__(nested_manifest, "entry_commitments", tampered_commitments)
    object.__setattr__(nested_manifest, "manifest_hash", tampered_commitments[-1])

    decision = IntakeGuard().evaluate(candidate)

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.TAMPERED_EVIDENCE in decision.reject_reasons


# ---------------------------------------------------------------------------
# Delegation boundary: what "evidence verified" does and does NOT mean
# ---------------------------------------------------------------------------


def test_manifest_linkage_and_completeness_are_delegated_to_service_boundary() -> None:
    """DELEGATION-BOUNDARY PIN (critic should-fix, 2026-07-14) — read this
    before trusting an ADMIT.

    Intake gate (b) verifies manifest INTEGRITY only: the supplied
    manifest's commitment chain must verify (`verify_manifest`) and its own
    `manifest_hash` must equal the candidate's claimed
    `evidence_bundle_manifest_hash`. Hash-equality is the ONLY linkage
    checked. Intake does NOT check:

    - outcome-LINKAGE: nothing ties the manifest's tenant/run/experiment
      scope to the candidate's source outcome. The manifest below is sealed
      for a completely UNRELATED tenant/run/experiment — and is ADMITTED
      the moment its own hash is what the candidate claims.
    - COMPLETENESS: the manifest below has ZERO `b_gate_decision` entries
      (`validate_completeness()` is False) — and is STILL admitted.

    Both checks are the w5-12 service boundary's obligation: w5-12 is the
    publisher that holds the real `BGateDecision` and must refuse to
    publish a `strategy.card.eligible.v1` for a pass verdict without a
    verified, COMPLETE evidence bundle bound to THAT outcome (see the
    intake module docstring's "Two admission surfaces" section and
    wave5-plan.md w5-12). Downstream consumers must NOT over-trust
    "evidence verified" at the intake layer: an ADMIT means exactly "the
    supplied manifest is internally intact and is the manifest the
    candidate's hash names" — nothing more.

    This test PINS the current admit behavior on purpose. If it ever fails
    because intake started rejecting on linkage/completeness, that is a
    DELIBERATE boundary move: update the intake module docstring and the
    w5-12 contract together, never silently.
    """
    from saena_domain.measurement.evidence import EvidenceKind, validate_completeness

    unrelated_manifest = build_manifest(
        tenant_id="totally-unrelated-co",
        run_id="run-9999",
        experiment_id="experiment-9999",
    )
    # Pin the premises: internally valid, yet INCOMPLETE for a B-gate-bearing
    # bundle — in particular it carries no b_gate_decision entry at all.
    assert not any(e.kind is EvidenceKind.B_GATE_DECISION for e in unrelated_manifest.entries)
    is_complete, missing = validate_completeness(unrelated_manifest)
    assert not is_complete
    assert EvidenceKind.B_GATE_DECISION in missing

    candidate = IntakeCandidate(
        card_candidate_ref="candidate-0001",
        evidence_bundle_manifest_hash=unrelated_manifest.manifest_hash,
        source_outcome=SourceOutcomeAssertion(
            b_verdict=BVerdict.PASS,
            provenance=SourceOutcomeProvenance.PRODUCTION,
            manifest=unrelated_manifest,
        ),
    )

    decision = IntakeGuard().evaluate(candidate)

    # CURRENT behavior, pinned deliberately: integrity-only verification admits.
    assert decision.status is IntakeDecisionStatus.ADMIT_AS_CANDIDATE
    assert decision.pool is CandidatePool.PRODUCTION


# ---------------------------------------------------------------------------
# Reject: tenant-id / raw-content smuggle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    ["tenant_id", "TenantId", "tenant-id", "run_id", "experiment_id", "workspace_id"],
)
def test_reject_tenant_identifying_field_smuggled_in_extra_payload(field_name: str) -> None:
    decision = IntakeGuard().evaluate(_candidate(extra_payload_fields={field_name: "acme-co"}))

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.TENANT_IDENTIFYING_FIELD in decision.reject_reasons


def test_reject_tenant_identifying_field_smuggled_nested() -> None:
    decision = IntakeGuard().evaluate(
        _candidate(extra_payload_fields={"context": {"nested": {"tenant_id": "acme-co"}}})
    )

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.TENANT_IDENTIFYING_FIELD in decision.reject_reasons


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("raw_content", "some raw customer html"),
        ("raw_response", "<html>full response</html>"),
        ("api_key", "sk-abcdefghijklmnopqrstuvwx"),
    ],
)
def test_reject_raw_content_field_smuggled(field_name: str, value: str) -> None:
    decision = IntakeGuard().evaluate(_candidate(extra_payload_fields={field_name: value}))

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.RAW_CONTENT_FIELD in decision.reject_reasons


def test_reject_secret_shaped_value_even_under_innocuous_field_name() -> None:
    decision = IntakeGuard().evaluate(_candidate(extra_payload_fields={"note": "sk-" + "x" * 30}))

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.RAW_CONTENT_FIELD in decision.reject_reasons


def test_reject_oversize_value_treated_as_raw_content() -> None:
    decision = IntakeGuard().evaluate(_candidate(extra_payload_fields={"note": "x" * 5000}))

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.RAW_CONTENT_FIELD in decision.reject_reasons


def test_reject_non_ascii_field_name_homoglyph_smuggling() -> None:
    """A field name that survives NFKC normalization but still contains
    non-ASCII characters (e.g. Cyrillic homoglyph of a Latin letter) is
    rejected fail-closed, mirroring the evidence-bundle guard's defense."""
    decision = IntakeGuard().evaluate(_candidate(extra_payload_fields={"tеnant": "acme-co"}))

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.TENANT_IDENTIFYING_FIELD in decision.reject_reasons


def test_reject_raw_content_nested_inside_a_list() -> None:
    """Sequence recursion: a secret-shaped value hidden inside a list value
    (not just a nested mapping) is still caught."""
    decision = IntakeGuard().evaluate(
        _candidate(extra_payload_fields={"notes": ["fine", "sk-" + "x" * 30]})
    )

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.RAW_CONTENT_FIELD in decision.reject_reasons


def test_list_of_clean_values_does_not_reject() -> None:
    decision = IntakeGuard().evaluate(
        _candidate(extra_payload_fields={"tags": ["alpha", "beta", "gamma"]})
    )

    assert decision.status is IntakeDecisionStatus.ADMIT_AS_CANDIDATE


def test_multiple_gate_failures_all_reported_together() -> None:
    decision = IntakeGuard().evaluate(
        _candidate(
            b_verdict=BVerdict.FAIL,
            manifest=None,
            manifest_hash=VALID_SHA_A,
            extra_payload_fields={"tenant_id": "acme-co"},
        )
    )

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.NOT_B_VERIFIED in decision.reject_reasons
    assert IntakeRejectReason.UNVERIFIABLE_EVIDENCE in decision.reject_reasons
    assert IntakeRejectReason.TENANT_IDENTIFYING_FIELD in decision.reject_reasons


# ---------------------------------------------------------------------------
# test-fixture → test-pool-only
# ---------------------------------------------------------------------------


def test_test_fixture_provenance_admits_only_into_test_pool() -> None:
    decision = IntakeGuard().evaluate(_candidate(provenance=SourceOutcomeProvenance.TEST_FIXTURE))

    assert decision.status is IntakeDecisionStatus.ADMIT_AS_CANDIDATE
    assert decision.pool is CandidatePool.TEST
    assert decision.pool is not CandidatePool.PRODUCTION


def test_production_provenance_never_lands_in_test_pool() -> None:
    decision = IntakeGuard().evaluate(_candidate(provenance=SourceOutcomeProvenance.PRODUCTION))

    assert decision.pool is CandidatePool.PRODUCTION


def test_no_operation_exists_to_move_a_candidate_between_pools() -> None:
    """Structural: `IntakeDecision` is frozen — there is no setter/method
    anywhere that reassigns an already-decided candidate's `pool` (e.g. to
    promote a TEST decision into PRODUCTION after the fact). Pool is a
    one-shot outcome of `evaluate`, never mutated afterward."""
    decision = IntakeGuard().evaluate(_candidate(provenance=SourceOutcomeProvenance.TEST_FIXTURE))
    assert decision.pool is CandidatePool.TEST

    with pytest.raises(ValidationError):
        decision.pool = CandidatePool.PRODUCTION  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Missing / malformed required fields → fail-closed
# ---------------------------------------------------------------------------


def test_reject_missing_card_candidate_ref_in_wire_payload() -> None:
    payload = build_strategy_card_eligible_payload()
    del payload["card_candidate_ref"]

    decision = IntakeGuard().evaluate_payload(
        payload,
        provenance=SourceOutcomeProvenance.PRODUCTION,
        manifest=build_manifest(),
    )

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.MISSING_REQUIRED_FIELD in decision.reject_reasons


def test_reject_missing_source_outcome_in_wire_payload() -> None:
    payload = build_strategy_card_eligible_payload()
    del payload["source_outcome"]

    decision = IntakeGuard().evaluate_payload(
        payload,
        provenance=SourceOutcomeProvenance.PRODUCTION,
        manifest=None,
    )

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.MISSING_REQUIRED_FIELD in decision.reject_reasons


def test_reject_missing_evidence_bundle_manifest_hash_in_wire_payload() -> None:
    payload = build_strategy_card_eligible_payload()
    del payload["source_outcome"]["evidence_bundle_manifest_hash"]

    decision = IntakeGuard().evaluate_payload(
        payload,
        provenance=SourceOutcomeProvenance.PRODUCTION,
        manifest=build_manifest(),
    )

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.MISSING_REQUIRED_FIELD in decision.reject_reasons


def test_reject_unknown_b_verdict_value_never_widens_admission() -> None:
    """An unrecognised `b_verdict` string (not pass/fail/undetermined) must
    be fail-closed REJECT, not silently coerced into a passing state."""
    payload = build_strategy_card_eligible_payload(b_verdict="mostly_pass")

    decision = IntakeGuard().evaluate_payload(
        payload,
        provenance=SourceOutcomeProvenance.PRODUCTION,
        manifest=build_manifest(),
    )

    assert decision.status is IntakeDecisionStatus.REJECT
    assert IntakeRejectReason.MISSING_REQUIRED_FIELD in decision.reject_reasons


def test_reject_malformed_source_outcome_shape_never_raises() -> None:
    payload = {"card_candidate_ref": "candidate-0001", "source_outcome": "not-an-object"}

    decision = IntakeGuard().evaluate_payload(
        payload,
        provenance=SourceOutcomeProvenance.PRODUCTION,
        manifest=None,
    )

    assert decision.status is IntakeDecisionStatus.REJECT


def test_candidate_construction_rejects_unknown_extra_field() -> None:
    """`extra="forbid"` on `IntakeCandidate`/`SourceOutcomeAssertion` — an
    attempted new top-level field this guard has no gate for is a
    construction-time rejection, never a silently-accepted widening."""
    manifest = build_manifest()
    with pytest.raises(ValidationError):
        IntakeCandidate(
            card_candidate_ref="candidate-0001",
            evidence_bundle_manifest_hash=manifest.manifest_hash,
            source_outcome=SourceOutcomeAssertion(
                b_verdict=BVerdict.PASS,
                provenance=SourceOutcomeProvenance.PRODUCTION,
                manifest=manifest,
            ),
            some_new_unmodeled_field="widen-me",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# API-surface structural test
# ---------------------------------------------------------------------------


_FORBIDDEN_METHOD_MARKERS = ("approve", "promote", "share", "learn", "publish")


def test_api_surface_structural_no_promote_approve_share_learn() -> None:
    """Structural pin (directive requirement 2): the intake module's public
    API surface contains NO callable whose name suggests
    approve/promote/share/learn semantics — intake is a dead end, not a
    staging area for an auto-promotion pipeline."""
    import saena_strategy_skill_bank.intake as intake_module

    public_names = [name for name in dir(intake_module) if not name.startswith("_")]
    offending = [
        name
        for name in public_names
        if any(marker in name.lower() for marker in _FORBIDDEN_METHOD_MARKERS)
    ]
    assert offending == [], f"forbidden-shaped names found on intake module: {offending}"

    guard_members = [name for name in dir(IntakeGuard) if not name.startswith("_")]
    offending_guard_members = [
        name
        for name in guard_members
        if any(marker in name.lower() for marker in _FORBIDDEN_METHOD_MARKERS)
    ]
    assert offending_guard_members == [], (
        f"forbidden-shaped members found on IntakeGuard: {offending_guard_members}"
    )

    package_public_names = [name for name in dir(ssb) if not name.startswith("_")]
    offending_package_members = [
        name
        for name in package_public_names
        if any(marker in name.lower() for marker in _FORBIDDEN_METHOD_MARKERS)
    ]
    assert offending_package_members == [], (
        f"forbidden-shaped names found on package __init__: {offending_package_members}"
    )

    # And every declared __all__ entry across both modules is free of the
    # forbidden markers too (belt-and-suspenders against a re-export that
    # `dir()` might not surface identically across Python versions).
    for exported in list(intake_module.__all__) + list(ssb.__all__):
        assert not any(marker in exported.lower() for marker in _FORBIDDEN_METHOD_MARKERS), (
            f"forbidden-shaped export: {exported}"
        )


def test_intake_guard_public_methods_are_exactly_evaluate_and_evaluate_payload() -> None:
    public_callables = [
        name
        for name in dir(IntakeGuard)
        if not name.startswith("_") and callable(getattr(IntakeGuard, name))
    ]
    assert set(public_callables) == {"evaluate", "evaluate_payload"}


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_equal_inputs_yield_equal_decision() -> None:
    manifest = build_manifest()
    candidate = IntakeCandidate(
        card_candidate_ref="candidate-0001",
        evidence_bundle_manifest_hash=manifest.manifest_hash,
        source_outcome=SourceOutcomeAssertion(
            b_verdict=BVerdict.PASS,
            provenance=SourceOutcomeProvenance.PRODUCTION,
            manifest=manifest,
        ),
    )

    guard = IntakeGuard()
    decisions = [guard.evaluate(candidate) for _ in range(5)]

    assert all(d == decisions[0] for d in decisions)


def test_determinism_reject_path_reason_ordering_is_stable() -> None:
    candidate = _candidate(
        b_verdict=BVerdict.FAIL,
        manifest=None,
        manifest_hash=VALID_SHA_A,
        extra_payload_fields={"tenant_id": "acme-co"},
    )

    guard = IntakeGuard()
    decisions = [guard.evaluate(candidate) for _ in range(5)]

    assert all(d.reject_reasons == decisions[0].reject_reasons for d in decisions)
    # Reason codes are sorted by wire value, independent of set iteration order.
    assert list(decisions[0].reject_reasons) == sorted(
        decisions[0].reject_reasons, key=lambda r: r.value
    )
