"""Discriminating + adversarial tests for the GRS policy interface (w5-07).

Design authority: wave5-plan.md E6 / H1 — "GRS: signed policy bundle,
missing/unsigned => fail-closed DENY/UNDETERMINED; TEST-ONLY fixture in tests;
production values BLOCKED(human)". This suite is the executable spec for the
MECHANISM only; it deliberately asserts nothing about what the "right"
production threshold numbers are (that is a human §13-7 decision).

Every fail-closed guard in ``grs.py`` has at least one test that FAILS if the
guard is removed (guard-mutation coverage): absent verifier, invalid
signature, hash mismatch, unsigned production, test-fixture-masquerade,
missing-threshold-default-pass, and the module-source "no hardcoded threshold"
structural test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from saena_domain.measurement import grs
from saena_domain.measurement.grs import (
    GrsDecision,
    GrsEligibility,
    GrsPolicyBundle,
    PolicyProvenance,
    PolicyRefusedError,
    ThresholdMissingError,
    compute_bundle_hash,
    evaluate_grs_eligibility,
    load_policy_bundle,
    make_test_fixture_policy,
)

from .conftest import (
    FIXTURE_VALUES,
    AcceptingVerifier,
    RaisingVerifier,
    RejectingVerifier,
    canonical_bundle_payload,
    denying_inputs,
    eligible_inputs,
    make_production_bundle,
    raw_production_bundle,
    signed_digest_for,
    valid_signature_for,
)

# --------------------------------------------------------------------------
# GrsPolicyBundle shape + hash
# --------------------------------------------------------------------------


def test_bundle_is_frozen() -> None:
    bundle = make_production_bundle()
    with pytest.raises((AttributeError, TypeError, ValueError)):
        bundle.version = "9.9.9"  # type: ignore[misc]


def test_bundle_hash_matches_canonical_of_values_version_provenance() -> None:
    bundle = make_production_bundle(version="1.2.3")
    expected_payload = canonical_bundle_payload(
        version="1.2.3", values=FIXTURE_VALUES, provenance="production"
    )
    from saena_domain.audit.canonical import sha256_hex

    assert bundle.bundle_hash == sha256_hex(expected_payload)


def test_bundle_hash_is_deterministic_across_key_insertion_order() -> None:
    a = GrsPolicyBundle(
        version="1.0.0",
        values={"min_grs": 0.7, "min_independent_layers": 2},
        provenance=PolicyProvenance.PRODUCTION,
    )
    b = GrsPolicyBundle(
        version="1.0.0",
        values={"min_independent_layers": 2, "min_grs": 0.7},
        provenance=PolicyProvenance.PRODUCTION,
    )
    assert a.bundle_hash == b.bundle_hash


def test_bundle_hash_changes_when_values_change() -> None:
    a = make_production_bundle(values={"min_grs": 0.7})
    b = make_production_bundle(values={"min_grs": 0.8})
    assert a.bundle_hash != b.bundle_hash


def test_bundle_hash_changes_when_provenance_changes() -> None:
    prod = GrsPolicyBundle(
        version="1.0.0", values=dict(FIXTURE_VALUES), provenance=PolicyProvenance.PRODUCTION
    )
    fixture = GrsPolicyBundle(
        version="1.0.0",
        values=dict(FIXTURE_VALUES),
        provenance=PolicyProvenance.TEST_FIXTURE,
        test_only=True,
    )
    assert prod.bundle_hash != fixture.bundle_hash


def test_production_bundle_with_test_only_marker_unconstructible() -> None:
    # Invariant (critic #2 should-fix 1): test_only must equal
    # (provenance is test_fixture) — production + test_only=True is a nonsense
    # state and must be rejected at construction.
    with pytest.raises(ValueError, match="test_only"):
        GrsPolicyBundle(
            version="1.0.0",
            values=dict(FIXTURE_VALUES),
            provenance=PolicyProvenance.PRODUCTION,
            test_only=True,
        )


def test_test_fixture_bundle_without_marker_unconstructible() -> None:
    # The mirror nonsense state: a test_fixture bundle NOT marked test_only
    # (the default) must also be rejected — an un-marked fixture is exactly
    # the masquerade shape is_production_valid exists to prevent.
    with pytest.raises(ValueError, match="test_only"):
        GrsPolicyBundle(
            version="1.0.0",
            values=dict(FIXTURE_VALUES),
            provenance=PolicyProvenance.TEST_FIXTURE,
        )


def test_bundle_rejects_non_semver_version() -> None:
    with pytest.raises(ValueError):
        GrsPolicyBundle(
            version="not-semver",
            values=dict(FIXTURE_VALUES),
            provenance=PolicyProvenance.PRODUCTION,
        )


def test_bundle_rejects_leading_zero_semver() -> None:
    # Repo-canonical semver (identifiers.schema.json #/$defs/semver) rejects
    # leading zeros — "01.0.0" is not a valid MAJOR part (critic #1 fix 1).
    with pytest.raises(ValueError):
        GrsPolicyBundle(
            version="01.0.0",
            values=dict(FIXTURE_VALUES),
            provenance=PolicyProvenance.PRODUCTION,
        )


def test_leading_zero_semver_refused_during_load() -> None:
    raw = {
        "version": "01.0.0",
        "values": dict(FIXTURE_VALUES),
        "provenance": "production",
    }
    with pytest.raises(PolicyRefusedError):
        load_policy_bundle(raw, signature="sig:whatever", verifier=AcceptingVerifier())


def test_bundle_accepts_semver_version() -> None:
    bundle = GrsPolicyBundle(
        version="10.20.30",
        values=dict(FIXTURE_VALUES),
        provenance=PolicyProvenance.PRODUCTION,
    )
    assert bundle.version == "10.20.30"


def test_compute_bundle_hash_helper_agrees_with_property() -> None:
    bundle = make_production_bundle()
    assert (
        compute_bundle_hash(
            version=bundle.version,
            values=bundle.values,
            provenance=bundle.provenance,
        )
        == bundle.bundle_hash
    )


def test_bundle_values_are_read_only_mapping() -> None:
    bundle = make_production_bundle()
    with pytest.raises((TypeError, AttributeError)):
        bundle.values["min_grs"] = 0.0  # type: ignore[index]


def test_bundle_hash_is_precomputed_and_cached() -> None:
    # MUST-FIX (critic #2 re-verify round 4): the digest is computed ONCE at
    # construction and cached — every read returns the SAME string object
    # (identity, not just equality), so no later read path recomputes the
    # canonical JSON and therefore none can raise.
    bundle = make_production_bundle()
    assert bundle.bundle_hash is bundle.bundle_hash


def test_fixture_factory_rejects_non_serializable_values_at_construction() -> None:
    # MUST-FIX (round 4): make_test_fixture_policy with a set value must fail
    # AT CONSTRUCTION (ValueError), not later as a raw TypeError inside
    # evaluate_grs_eligibility's decision-record bundle_hash access.
    with pytest.raises(ValueError, match="non-serializable"):
        make_test_fixture_policy(values={"k": {1, 2}})


def test_direct_construction_rejects_non_serializable_bytes_value() -> None:
    # Same root guard, direct-construction path: bytes are not canonical-JSON
    # serializable — refused at construction, uniformly with the factory and
    # loader paths.
    with pytest.raises(ValueError, match="non-serializable"):
        GrsPolicyBundle(
            version="1.0.0",
            values={"k": b"raw-bytes"},
            provenance=PolicyProvenance.PRODUCTION,
        )


# --------------------------------------------------------------------------
# load_policy_bundle — happy path
# --------------------------------------------------------------------------


def test_load_production_bundle_with_valid_signature_succeeds() -> None:
    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    bundle = load_policy_bundle(raw, signature=sig, verifier=AcceptingVerifier())
    assert bundle.provenance is PolicyProvenance.PRODUCTION
    assert bundle.version == "1.0.0"
    assert dict(bundle.values) == dict(FIXTURE_VALUES)


# --------------------------------------------------------------------------
# load_policy_bundle — ADVERSARIAL / fail-closed (guard mutation)
# --------------------------------------------------------------------------


def test_absent_verifier_refused_even_with_signature() -> None:
    # GUARD: verifier absent => REFUSED. Removing the None-check would let an
    # unverifiable production bundle load. Reason string pinned (critic #2
    # should-fix 2) so this test fails only when THIS guard is removed, not
    # when a different earlier refusal happens to fire.
    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    with pytest.raises(PolicyRefusedError, match="requires a verifier"):
        load_policy_bundle(raw, signature=sig, verifier=None)


def test_invalid_signature_refused() -> None:
    # GUARD: verifier verdict not True => REFUSED (reason pinned).
    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    with pytest.raises(PolicyRefusedError, match="verification failed"):
        load_policy_bundle(raw, signature=sig, verifier=RejectingVerifier())


def test_unsigned_production_bundle_refused() -> None:
    # GUARD: provenance=production REQUIRES a signature; None signature refused
    # BEFORE any verifier call. Reason pinned to the signature-requirement
    # guard specifically (critic #2 should-fix 2): this test must fail for the
    # RIGHT reason — if this guard is removed, the bundle would still be
    # refused downstream (verify(None) mismatch), but with a DIFFERENT reason,
    # and this assertion catches exactly that substitution.
    raw = raw_production_bundle()
    with pytest.raises(PolicyRefusedError, match="requires a signature"):
        load_policy_bundle(raw, signature=None, verifier=AcceptingVerifier())


def test_tampered_values_hash_mismatch_refused() -> None:
    # GUARD: the signed digest is bound to the ORIGINAL values; tampering the
    # values after signing yields a hash the accepting verifier will not match.
    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    # Attacker swaps in a laxer threshold after the signature was produced.
    raw["values"]["min_grs"] = 0.0
    with pytest.raises(PolicyRefusedError, match="verification failed"):
        load_policy_bundle(raw, signature=sig, verifier=AcceptingVerifier())


def test_tampered_version_hash_mismatch_refused() -> None:
    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    raw["version"] = "2.0.0"
    with pytest.raises(PolicyRefusedError, match="verification failed"):
        load_policy_bundle(raw, signature=sig, verifier=AcceptingVerifier())


def test_provenance_tampered_to_production_but_signed_as_fixture_refused() -> None:
    # A signature legitimately produced for a test_fixture digest must NOT
    # verify once provenance is flipped to production (provenance is inside the
    # signed payload).
    raw = raw_production_bundle()
    fixture_sig = valid_signature_for(
        version="1.0.0", values=FIXTURE_VALUES, provenance="test_fixture"
    )
    with pytest.raises(PolicyRefusedError, match="verification failed"):
        load_policy_bundle(raw, signature=fixture_sig, verifier=AcceptingVerifier())


def test_raising_verifier_is_fail_closed_refused() -> None:
    # GUARD: an exception from verify() must be caught and converted to
    # REFUSED, never propagated as an accidental allow (or an uncaught crash
    # that a caller might mishandle as "not denied").
    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    with pytest.raises(PolicyRefusedError, match="verifier raised"):
        load_policy_bundle(raw, signature=sig, verifier=RaisingVerifier())


@pytest.mark.parametrize(
    "verdict",
    ["false", "true", 1, object(), None, [True]],
    ids=["str-false", "str-true", "int-1", "object", "none", "list-true"],
)
def test_non_bool_verifier_verdict_refused(verdict: object) -> None:
    # MUST-FIX (critic #2): STRICT acceptance — a verifier returning any
    # truthy (or falsy) NON-True value must be refused. A truthiness check
    # (`if not accepted`) fails OPEN for "false"/"true"/1/object(): all truthy,
    # all would have loaded a production bundle. Only the literal bool True
    # accepts (`accepted is not True` — identity, so even 1 == True is
    # refused). Reason pinned to the verification-verdict guard.
    class VerdictVerifier:
        def __init__(self, value: object) -> None:
            self._value = value

        def verify(self, signed_digest: str, signature: str) -> object:
            return self._value

    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    with pytest.raises(PolicyRefusedError, match="verification failed"):
        # The protocol violation (verify -> object, not bool) is the POINT of
        # this adversarial double — a misbehaving verifier implementation.
        load_policy_bundle(raw, signature=sig, verifier=VerdictVerifier(verdict))  # type: ignore[arg-type]


def test_only_literal_true_verdict_accepted() -> None:
    # The strict-acceptance mirror: a verifier returning the literal bool True
    # (and only that) loads the bundle. Guard-mutation pair for the test
    # above — `is True`-strictness must not be over-tightened into
    # never-accepting either.
    class LiteralTrueVerifier:
        def verify(self, signed_digest: str, signature: str) -> bool:
            return True

    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    bundle = load_policy_bundle(raw, signature=sig, verifier=LiteralTrueVerifier())
    assert bundle.provenance is PolicyProvenance.PRODUCTION


def test_unsigned_test_fixture_provenance_via_loader_still_refused() -> None:
    # A raw bundle CLAIMING provenance=test_fixture cannot be loaded unsigned
    # through the normal loader — the ONLY unsigned test-fixture path is the
    # explicit make_test_fixture_policy() factory. This stops a hostile raw
    # payload from self-declaring test_fixture to dodge the signature rule.
    # Reason pinned to the fixture-masquerade guard specifically (critic #2
    # should-fix 2): without the pin, removing this guard could still refuse
    # via the downstream signature guard and the test would pass for the
    # WRONG reason.
    raw = {
        "version": "1.0.0",
        "values": dict(FIXTURE_VALUES),
        "provenance": "test_fixture",
    }
    with pytest.raises(PolicyRefusedError, match="make_test_fixture_policy"):
        load_policy_bundle(raw, signature=None, verifier=AcceptingVerifier())


def test_signed_test_fixture_via_loader_also_refused() -> None:
    # Even a CORRECTLY SIGNED test_fixture payload is refused by the loader —
    # the fixture path is factory-only, signature or not (the guard is about
    # the loading channel, not merely about missing signatures).
    raw = {
        "version": "1.0.0",
        "values": dict(FIXTURE_VALUES),
        "provenance": "test_fixture",
    }
    fixture_sig = valid_signature_for(
        version="1.0.0", values=FIXTURE_VALUES, provenance="test_fixture"
    )
    with pytest.raises(PolicyRefusedError, match="make_test_fixture_policy"):
        load_policy_bundle(raw, signature=fixture_sig, verifier=AcceptingVerifier())


def test_unknown_provenance_value_refused() -> None:
    raw = {
        "version": "1.0.0",
        "values": dict(FIXTURE_VALUES),
        "provenance": "staging",
    }
    with pytest.raises(PolicyRefusedError, match="unrecognized provenance"):
        load_policy_bundle(raw, signature="whatever", verifier=AcceptingVerifier())


def test_missing_provenance_key_refused() -> None:
    raw = {"version": "1.0.0", "values": dict(FIXTURE_VALUES)}
    with pytest.raises(PolicyRefusedError):
        load_policy_bundle(raw, signature="whatever", verifier=AcceptingVerifier())


def test_missing_version_key_refused() -> None:
    raw = {"values": dict(FIXTURE_VALUES), "provenance": "production"}
    with pytest.raises(PolicyRefusedError):
        load_policy_bundle(raw, signature="whatever", verifier=AcceptingVerifier())


def test_missing_values_key_refused() -> None:
    raw = {"version": "1.0.0", "provenance": "production"}
    with pytest.raises(PolicyRefusedError):
        load_policy_bundle(raw, signature="whatever", verifier=AcceptingVerifier())


def test_non_mapping_raw_refused() -> None:
    with pytest.raises(PolicyRefusedError):
        load_policy_bundle(
            ["not", "a", "mapping"],
            signature="whatever",
            verifier=AcceptingVerifier(),
        )


def test_non_mapping_values_refused() -> None:
    raw = {"version": "1.0.0", "values": ["a", "b"], "provenance": "production"}
    with pytest.raises(PolicyRefusedError):
        load_policy_bundle(raw, signature="whatever", verifier=AcceptingVerifier())


def test_non_serializable_values_refused_not_typeerror() -> None:
    # GUARD (critic #1 fix 2): a values mapping that canonical_json cannot
    # serialize (a set here) must surface as PolicyRefusedError per the
    # loader's contract — never leak the underlying TypeError. The digest
    # computation sits inside the refusal boundary.
    raw = {
        "version": "1.0.0",
        "values": {"k": {1, 2, 3}},
        "provenance": "production",
    }
    with pytest.raises(PolicyRefusedError, match="non-serializable"):
        load_policy_bundle(raw, signature="sig:whatever", verifier=AcceptingVerifier())


def test_non_string_version_refused() -> None:
    raw = {"version": 100, "values": dict(FIXTURE_VALUES), "provenance": "production"}
    with pytest.raises(PolicyRefusedError):
        load_policy_bundle(raw, signature="whatever", verifier=AcceptingVerifier())


def test_non_semver_production_version_refused_during_load() -> None:
    # A production payload whose version is a string but NOT semver is refused
    # (the GrsPolicyBundle constructor's ValueError is converted to REFUSED,
    # fail-closed) — reached AFTER the signature/verifier presence checks, so
    # a real signature + verifier are supplied to exercise the malformed path.
    raw = {
        "version": "not-semver",
        "values": dict(FIXTURE_VALUES),
        "provenance": "production",
    }
    with pytest.raises(PolicyRefusedError):
        load_policy_bundle(raw, signature="sig:whatever", verifier=AcceptingVerifier())


def test_verifier_receives_bound_signed_digest() -> None:
    # The verifier must be handed the digest that is actually bound to the
    # bundle content (defense against a verifier that only ever sees a constant
    # / attacker-chosen digest).
    seen: dict[str, str] = {}

    class RecordingVerifier:
        def verify(self, signed_digest: str, signature: str) -> bool:
            seen["digest"] = signed_digest
            seen["sig"] = signature
            return signature == "sig:" + signed_digest

    raw = raw_production_bundle()
    sig = valid_signature_for(version="1.0.0", values=FIXTURE_VALUES, provenance="production")
    load_policy_bundle(raw, signature=sig, verifier=RecordingVerifier())
    assert seen["digest"] == signed_digest_for(
        version="1.0.0", values=FIXTURE_VALUES, provenance="production"
    )


# --------------------------------------------------------------------------
# make_test_fixture_policy — TEST-ONLY path
# --------------------------------------------------------------------------


def test_make_test_fixture_policy_produces_test_fixture_provenance() -> None:
    bundle = make_test_fixture_policy(values=dict(FIXTURE_VALUES))
    assert bundle.provenance is PolicyProvenance.TEST_FIXTURE


def test_make_test_fixture_policy_sets_test_only_marker() -> None:
    bundle = make_test_fixture_policy(values=dict(FIXTURE_VALUES))
    assert bundle.test_only is True


def test_production_bundle_test_only_is_false() -> None:
    assert make_production_bundle().test_only is False


def test_factory_name_and_docstring_scream_test_only() -> None:
    # The directive requires the factory's NAME/docstring to make its
    # test-only nature unmistakable — pinned so a rename that hides it fails.
    assert "test" in make_test_fixture_policy.__name__.lower()
    assert make_test_fixture_policy.__doc__ is not None
    assert "TEST-ONLY" in make_test_fixture_policy.__doc__


def test_fixture_bundle_default_values_present() -> None:
    # Calling the factory with no explicit values still yields a usable,
    # non-production fixture (default values are TEST-ONLY, allowed to exist).
    bundle = make_test_fixture_policy()
    assert bundle.provenance is PolicyProvenance.TEST_FIXTURE
    assert bundle.test_only is True


# --------------------------------------------------------------------------
# evaluate_grs_eligibility
# --------------------------------------------------------------------------


def test_no_bundle_is_undetermined_policy_missing() -> None:
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=None)
    assert decision.decision is GrsEligibility.UNDETERMINED
    assert decision.reason == "grs_policy_missing"
    assert decision.policy_version is None
    assert decision.bundle_hash is None
    assert decision.provenance is None
    assert decision.is_production_valid is False


def test_eligible_inputs_against_production_bundle() -> None:
    bundle = make_production_bundle()
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=bundle)
    assert isinstance(decision, GrsDecision)
    assert decision.decision is GrsEligibility.ELIGIBLE
    assert decision.is_production_valid is True


def test_denying_inputs_against_production_bundle() -> None:
    bundle = make_production_bundle()
    decision = evaluate_grs_eligibility(denying_inputs(), bundle=bundle)
    assert decision.decision is GrsEligibility.DENY


def test_missing_required_threshold_denies_not_default_passes() -> None:
    # GUARD (fail-closed core): a bundle missing a required threshold key must
    # DENY, naming the missing key — NEVER fall back to a default and pass.
    bundle = make_production_bundle(values={"min_grs": 0.7})  # missing others
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=bundle)
    assert decision.decision is GrsEligibility.DENY
    assert "min_independent_layers" in decision.reason


def test_missing_threshold_denies_even_when_inputs_would_pass_present_ones() -> None:
    # Even inputs that clear every PRESENT threshold must still DENY if a
    # required threshold key is absent — the absence itself is the denial.
    bundle = make_production_bundle(values={"min_grs": 0.0, "min_independent_layers": 0})
    # max_open_incidents missing.
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=bundle)
    assert decision.decision is GrsEligibility.DENY
    assert "max_open_incidents" in decision.reason


def test_decision_carries_policy_version_hash_provenance() -> None:
    bundle = make_production_bundle(version="3.1.4")
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=bundle)
    assert decision.policy_version == "3.1.4"
    assert decision.bundle_hash == bundle.bundle_hash
    assert decision.provenance is PolicyProvenance.PRODUCTION


def test_deny_decision_still_carries_policy_metadata() -> None:
    # Audit requirement: EVERY decision (even DENY on missing threshold) must
    # carry version + bundle_hash + provenance.
    bundle = make_production_bundle(version="3.1.4", values={"min_grs": 0.7})
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=bundle)
    assert decision.decision is GrsEligibility.DENY
    assert decision.policy_version == "3.1.4"
    assert decision.bundle_hash == bundle.bundle_hash
    assert decision.provenance is PolicyProvenance.PRODUCTION


def test_test_fixture_decision_is_not_production_valid() -> None:
    # GUARD (mechanism PASS / production BLOCKED separation): a decision made
    # against a test_fixture bundle keeps is_production_valid == False even
    # when the eligibility outcome is ELIGIBLE.
    bundle = make_test_fixture_policy(values=dict(FIXTURE_VALUES))
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=bundle)
    assert decision.decision is GrsEligibility.ELIGIBLE
    assert decision.is_production_valid is False
    assert decision.provenance is PolicyProvenance.TEST_FIXTURE


def test_forged_production_bundle_with_test_only_marker_not_production_valid() -> None:
    # SF-1 (critic #2 re-verify round 4): the `test_only is False` conjunct in
    # is_production_valid must be LIVE, not dead code shadowed by the
    # construction invariant. Forge the invariant-violating state the ctor
    # forbids (production provenance + test_only=True) by bypassing __init__/
    # __post_init__ entirely — the defense-in-depth conjunct must still report
    # NOT production-valid. Dropping `and bundle.test_only is False` from
    # evaluate_grs_eligibility fails exactly this test.
    forged = object.__new__(GrsPolicyBundle)
    object.__setattr__(forged, "version", "1.0.0")
    object.__setattr__(forged, "values", dict(FIXTURE_VALUES))
    object.__setattr__(forged, "provenance", PolicyProvenance.PRODUCTION)
    object.__setattr__(forged, "test_only", True)
    object.__setattr__(forged, "_bundle_hash", "forged-unverified-digest")
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=forged)
    assert decision.decision is GrsEligibility.ELIGIBLE
    assert decision.is_production_valid is False


def test_missing_input_field_denies() -> None:
    # An input missing a field a present threshold requires => DENY, not crash
    # and not default-pass.
    bundle = make_production_bundle()
    decision = evaluate_grs_eligibility({"grs": 0.9}, bundle=bundle)
    assert decision.decision is GrsEligibility.DENY


def test_non_numeric_threshold_value_denies_not_typeerror() -> None:
    # GUARD (critic #2 should-fix 3): a bundle whose threshold value cannot be
    # compared against the input (a string vs a float) must produce DENY with
    # a taxonomy reason naming the threshold key — never leak a raw TypeError
    # and never be treated as a pass.
    values = dict(FIXTURE_VALUES)
    values["min_grs"] = "high"
    bundle = make_production_bundle(values=values)
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=bundle)
    assert decision.decision is GrsEligibility.DENY
    assert decision.reason == "grs_malformed_threshold_value:min_grs"
    # Audit metadata still present on this DENY.
    assert decision.bundle_hash == bundle.bundle_hash
    assert decision.provenance is PolicyProvenance.PRODUCTION


def test_non_numeric_input_value_denies_not_typeerror() -> None:
    # The mirror shape: the INPUT side being incomparable is the same
    # fail-closed DENY (the comparison, not the side, is what cannot clear).
    bundle = make_production_bundle()
    inputs = dict(eligible_inputs())
    inputs["grs"] = "very high"
    decision = evaluate_grs_eligibility(inputs, bundle=bundle)
    assert decision.decision is GrsEligibility.DENY
    assert decision.reason == "grs_malformed_threshold_value:min_grs"


def test_decision_is_frozen() -> None:
    decision = evaluate_grs_eligibility(eligible_inputs(), bundle=make_production_bundle())
    with pytest.raises((AttributeError, TypeError, ValueError)):
        decision.decision = GrsEligibility.DENY  # type: ignore[misc]


# --------------------------------------------------------------------------
# strict accessor
# --------------------------------------------------------------------------


def test_strict_accessor_raises_threshold_missing() -> None:
    bundle = make_production_bundle(values={"min_grs": 0.7})
    with pytest.raises(ThresholdMissingError):
        bundle.require_threshold("min_independent_layers")


def test_strict_accessor_returns_present_value() -> None:
    bundle = make_production_bundle()
    assert bundle.require_threshold("min_grs") == FIXTURE_VALUES["min_grs"]


# --------------------------------------------------------------------------
# STRUCTURAL: no hardcoded production thresholds in the module source
# --------------------------------------------------------------------------


def _code_number_tokens(source: str) -> list[str]:
    """Every NUMBER token in `source` that is real executable code — comments
    and string/docstring bodies are excluded via `tokenize`, so date/id prose
    like ``w5-07`` or ``§13-7`` in a docstring never counts as a code literal.
    This is the honest form of "no threshold constant baked into the code":
    it inspects the tokens the interpreter actually evaluates, not prose."""
    import io
    import tokenize

    numbers: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.NUMBER:
            numbers.append(tok.string)
    return numbers


def test_module_source_contains_no_numeric_threshold_constants() -> None:
    """No float literal, and no non-structural int literal, may appear as an
    EXECUTABLE-CODE token in the module — a fallback threshold would be exactly
    such a literal, and the mechanism must never bake one in. Values come ONLY
    from the signed bundle. (Docstrings/comments are excluded — see
    ``_code_number_tokens`` — a date or unit-id in prose is not a constant.)
    """
    numbers = _code_number_tokens(Path(grs.__file__).read_text(encoding="utf-8"))

    float_literals = [n for n in numbers if ("." in n or "e" in n.lower())]
    assert float_literals == [], f"unexpected float literals in code: {float_literals}"

    # The ONLY int literals tolerated are structural (there should be none, in
    # fact — semver is regex-matched, not integer-indexed, and the fixture
    # version is assembled from str(len(...))). Enumerated allowlist kept tiny.
    allowed_ints = {"0", "1", "2", "3"}
    int_literals = [n for n in numbers if n not in allowed_ints]
    assert int_literals == [], f"unexpected int literals (possible thresholds): {int_literals}"


def test_no_default_values_in_require_threshold() -> None:
    # A structural guarantee: require_threshold must not accept a default=
    # parameter that would let a caller silently supply a fallback threshold.
    import inspect

    sig = inspect.signature(GrsPolicyBundle.require_threshold)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert len(params) == 1, "require_threshold must take exactly the key — no default"
    assert params[0].default is inspect.Parameter.empty


# --------------------------------------------------------------------------
# error type shapes
# --------------------------------------------------------------------------


def test_policy_refused_error_carries_reason() -> None:
    raw = raw_production_bundle()
    try:
        load_policy_bundle(raw, signature=None, verifier=AcceptingVerifier())
    except PolicyRefusedError as exc:
        assert str(exc)
        assert exc.reason
    else:  # pragma: no cover - the call above must raise
        pytest.fail("expected PolicyRefusedError")
