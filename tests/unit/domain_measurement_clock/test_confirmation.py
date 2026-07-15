"""Discriminating tests for saena_domain.measurement.confirmation (w5-03).

Every test is designed to FAIL against a naive/faulty implementation: each
guard has at least one test that flips an assertion if that guard is deleted
(guard-mutation discipline, wave5-plan.md §Test/evidence requirements).
Adversarial cases required by the directive are grouped at the bottom.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from saena_domain.measurement.confirmation import (
    Accepted,
    DeploymentConfirmation,
    Duplicate,
    Rejected,
    RejectionReason,
    validate_confirmation,
)

from .conftest import (
    REG_CREATED_AT,
    SERVER_RECEIVED_AT,
    accepting_verifier,
    confirmation,
    registration_view,
    rejecting_verifier,
)

# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_valid_confirmation_is_accepted() -> None:
    verdict = validate_confirmation(
        confirmation(), registration_view(), SERVER_RECEIVED_AT, accepting_verifier(), {}
    )
    assert isinstance(verdict, Accepted)
    assert verdict.server_received_at == SERVER_RECEIVED_AT
    assert verdict.content_fingerprint.startswith("sha256:")


def test_accepted_uses_server_received_at_as_the_anchor_not_confirmed_at() -> None:
    """Timestamp authority is server_received_at, NOT the payload confirmed_at.
    A confirmation whose confirmed_at differs from server_received_at (but is
    still within skew/backdate bounds) still anchors on server_received_at."""
    earlier_claim = SERVER_RECEIVED_AT - timedelta(hours=1)
    verdict = validate_confirmation(
        confirmation(confirmed_at=earlier_claim),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Accepted)
    assert verdict.server_received_at == SERVER_RECEIVED_AT
    assert verdict.confirmation.confirmed_at == earlier_claim


def test_artifact_hash_only_is_accepted() -> None:
    """Either deployed_commit_sha OR artifact_hash suffices."""
    verdict = validate_confirmation(
        confirmation(deployed_commit_sha=None, artifact_hash="sha256:" + "f" * 64),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Accepted)


# --------------------------------------------------------------------------- #
# Identity binding (guard: tenant / run / project / site / experiment)
# --------------------------------------------------------------------------- #


def test_cross_tenant_confirmation_is_rejected_as_cross_tenant_replay() -> None:
    verdict = validate_confirmation(
        confirmation(tenant_id="evil-co"),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.CROSS_TENANT_REPLAY


def test_cross_tenant_rejection_does_not_leak_expected_tenant() -> None:
    """Non-leaking: the rejection names the reference (idempotency key /
    experiment id) but never echoes the expected vs. presented tenant — so it
    cannot be used as a tenant-identity oracle."""
    verdict = validate_confirmation(
        confirmation(tenant_id="evil-co"),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    dumped = verdict.model_dump()
    assert "acme-co" not in str(dumped)
    assert "evil-co" not in str(dumped)


@pytest.mark.parametrize("field", ["run_id", "project", "site", "experiment_id"])
def test_non_tenant_identity_mismatch_is_rejected(field: str) -> None:
    verdict = validate_confirmation(
        confirmation(**{field: "mismatched-value"}),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.IDENTITY_MISMATCH


# --------------------------------------------------------------------------- #
# Deployed-artifact + deployment-target identity
# --------------------------------------------------------------------------- #


def test_missing_both_commit_and_artifact_is_rejected() -> None:
    verdict = validate_confirmation(
        confirmation(deployed_commit_sha=None, artifact_hash=None),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.MISSING_DEPLOY_ARTIFACT


def test_missing_deployment_target_is_rejected() -> None:
    verdict = validate_confirmation(
        confirmation(deployment_target=None),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.MISSING_DEPLOYMENT_TARGET


# --------------------------------------------------------------------------- #
# Trusted confirmer (fail-closed; never default-accept)
# --------------------------------------------------------------------------- #


def test_absent_verifier_is_rejected_never_default_accepted() -> None:
    verdict = validate_confirmation(
        confirmation(), registration_view(), SERVER_RECEIVED_AT, None, {}
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.UNTRUSTED_CONFIRMER


def test_failed_verification_is_rejected() -> None:
    verdict = validate_confirmation(
        confirmation(),
        registration_view(),
        SERVER_RECEIVED_AT,
        rejecting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.CONFIRMER_VERIFICATION_FAILED


@pytest.mark.parametrize(
    "truthy_result",
    ["yes", 1, object(), [True], (True,)],
    ids=["str-yes", "int-1", "object", "list-of-true", "tuple-of-true"],
)
def test_truthy_but_not_true_verifier_result_is_rejected(truthy_result: object) -> None:
    """Strict bool identity (critic #2): verification demands a LITERAL True.
    A verifier returning a merely truthy value ('yes', 1, object(), ...) is
    treated as verification failure — truthiness is not verification.
    Weakening the guard back to `if not verify(...)` flips this test."""

    class TruthyVerifier:
        def verify(self, c: DeploymentConfirmation) -> bool:
            return truthy_result  # type: ignore[return-value]

    verdict = validate_confirmation(
        confirmation(), registration_view(), SERVER_RECEIVED_AT, TruthyVerifier(), {}
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.CONFIRMER_VERIFICATION_FAILED


def test_verifier_receives_the_confirmation() -> None:
    """The injected verifier is actually consulted with the confirmation —
    not bypassed."""
    seen: list[DeploymentConfirmation] = []

    class RecordingVerifier:
        def verify(self, c: DeploymentConfirmation) -> bool:
            seen.append(c)
            return True

    c = confirmation()
    validate_confirmation(c, registration_view(), SERVER_RECEIVED_AT, RecordingVerifier(), {})
    assert seen == [c]


# --------------------------------------------------------------------------- #
# Timestamp authority: backdate / future spoof
# --------------------------------------------------------------------------- #


def test_backdated_confirmation_before_registration_is_rejected() -> None:
    """confirmed_at earlier than the registration created/approved time is a
    backdate spoof — reject."""
    verdict = validate_confirmation(
        confirmation(confirmed_at=REG_CREATED_AT - timedelta(seconds=1)),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.BACKDATED_CONFIRMATION


def test_confirmed_at_exactly_at_earliest_valid_is_accepted() -> None:
    """Boundary: confirmed_at == earliest(created_at, approved_at) is NOT
    backdated (uses < not <=)."""
    verdict = validate_confirmation(
        confirmation(confirmed_at=REG_CREATED_AT),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Accepted)


def test_future_confirmation_beyond_skew_is_rejected() -> None:
    verdict = validate_confirmation(
        confirmation(confirmed_at=SERVER_RECEIVED_AT + timedelta(seconds=1)),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
        allowed_skew_seconds=0,
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.FUTURE_CONFIRMATION


def test_future_confirmation_within_skew_is_accepted() -> None:
    verdict = validate_confirmation(
        confirmation(confirmed_at=SERVER_RECEIVED_AT + timedelta(seconds=30)),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
        allowed_skew_seconds=60,
    )
    assert isinstance(verdict, Accepted)


def test_future_confirmation_exactly_at_skew_boundary_is_accepted() -> None:
    """Boundary: confirmed_at == server_received_at + skew is accepted (uses >)."""
    verdict = validate_confirmation(
        confirmation(confirmed_at=SERVER_RECEIVED_AT + timedelta(seconds=60)),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
        allowed_skew_seconds=60,
    )
    assert isinstance(verdict, Accepted)


def test_negative_skew_is_rejected_fail_closed() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        validate_confirmation(
            confirmation(),
            registration_view(),
            SERVER_RECEIVED_AT,
            accepting_verifier(),
            {},
            allowed_skew_seconds=-1,
        )


# --------------------------------------------------------------------------- #
# Linkage: registration_canonical_hash
# --------------------------------------------------------------------------- #


def test_unknown_registration_hash_is_rejected() -> None:
    verdict = validate_confirmation(
        confirmation(registration_canonical_hash="sha256:" + "0" * 64),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.UNKNOWN_REGISTRATION


# --------------------------------------------------------------------------- #
# Idempotency / replay
# --------------------------------------------------------------------------- #


def test_byte_identical_replay_is_duplicate_no_state_change() -> None:
    c = confirmation()
    rv = registration_view()
    first = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    assert isinstance(first, Accepted)
    prior = {c.idempotency_key: first}
    replay = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), prior)
    assert isinstance(replay, Duplicate)
    # Same window/anchor observed — the ORIGINAL accepted verdict, unchanged.
    assert replay.accepted is first
    # Prior state was not mutated.
    assert prior == {c.idempotency_key: first}


def test_same_key_different_content_is_conflicting_replay() -> None:
    c = confirmation()
    rv = registration_view()
    first = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    assert isinstance(first, Accepted)
    prior = {c.idempotency_key: first}
    # Same idempotency key, DIFFERENT content (different commit sha).
    conflicting = confirmation(deployed_commit_sha="b" * 40)
    verdict = validate_confirmation(
        conflicting, rv, SERVER_RECEIVED_AT, accepting_verifier(), prior
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.CONFLICTING_REPLAY


def test_conflicting_replay_never_re_accepts_or_picks_a_winner() -> None:
    """A conflicting replay is fail-closed reject — it must NOT return an
    Accepted (which would let a second, different confirmation silently win)."""
    c = confirmation()
    rv = registration_view()
    first = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    prior = {c.idempotency_key: first}
    verdict = validate_confirmation(
        confirmation(deployment_target="prod/evil/edge"),
        rv,
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        prior,
    )
    assert not isinstance(verdict, Accepted)


def test_duplicate_check_precedes_trust_extension() -> None:
    """A byte-identical replay is a Duplicate even when NO verifier is passed
    on the replay call — idempotency is decided before trust is re-extended,
    so a re-delivery of an already-accepted confirmation is a stable no-op."""
    c = confirmation()
    rv = registration_view()
    first = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    prior = {c.idempotency_key: first}
    replay = validate_confirmation(c, rv, SERVER_RECEIVED_AT, None, prior)
    assert isinstance(replay, Duplicate)


def test_cross_tenant_key_collision_is_tenant_reject_not_conflicting_replay() -> None:
    """Tenant-first ordering (critic #2): a foreign tenant colliding on the
    SAME idempotency key is rejected as cross_tenant_replay — identity binding
    runs BEFORE the idempotency lookup, so the collision can never surface
    another tenant's prior state as conflicting_replay (or as a Duplicate).
    Reordering idempotency back in front of identity binding flips this test."""
    c = confirmation()
    rv = registration_view()
    first = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    assert isinstance(first, Accepted)
    prior = {c.idempotency_key: first}

    foreign = confirmation(tenant_id="evil-co")  # same idempotency key, other tenant
    verdict = validate_confirmation(foreign, rv, SERVER_RECEIVED_AT, accepting_verifier(), prior)
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.CROSS_TENANT_REPLAY
    assert verdict.reason_code != RejectionReason.CONFLICTING_REPLAY
    # Tenant A's prior state is untouched by tenant B's submission.
    assert prior == {c.idempotency_key: first}


def test_identity_mismatch_key_collision_is_identity_reject_not_conflicting_replay() -> None:
    """Same ordering guarantee for non-tenant identity fields: a same-tenant
    submission with a colliding key but a different run_id is an
    identity_mismatch, never a conflicting_replay against the other run's
    prior state."""
    c = confirmation()
    rv = registration_view()
    first = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    assert isinstance(first, Accepted)
    prior = {c.idempotency_key: first}

    other_run = confirmation(run_id="run-other")
    verdict = validate_confirmation(other_run, rv, SERVER_RECEIVED_AT, accepting_verifier(), prior)
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.IDENTITY_MISMATCH
    assert prior == {c.idempotency_key: first}


# --------------------------------------------------------------------------- #
# Timezone discipline: naive datetimes rejected
# --------------------------------------------------------------------------- #


def test_naive_server_received_at_is_rejected() -> None:
    naive = SERVER_RECEIVED_AT.replace(tzinfo=None)
    verdict = validate_confirmation(
        confirmation(), registration_view(), naive, accepting_verifier(), {}
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.NAIVE_TIMESTAMP


def test_naive_confirmed_at_is_rejected() -> None:
    verdict = validate_confirmation(
        confirmation(confirmed_at=SERVER_RECEIVED_AT.replace(tzinfo=None)),
        registration_view(),
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code == RejectionReason.NAIVE_TIMESTAMP


# --------------------------------------------------------------------------- #
# Model construction hardening
# --------------------------------------------------------------------------- #


def test_confirmation_rejects_unknown_field() -> None:
    with pytest.raises(ValueError):
        DeploymentConfirmation(
            experiment_id="e",
            tenant_id="t",
            run_id="r",
            project="p",
            site="s",
            registration_canonical_hash="h",
            confirmed_at=SERVER_RECEIVED_AT,
            idempotency_key="k",
            confirmer_identity="ci",
            confirmer_signature="sig",
            stray_field="x",
        )


def test_confirmation_rejects_whitespace_only_deployment_target() -> None:
    with pytest.raises(ValueError, match="whitespace-only"):
        confirmation(deployment_target="   ")


def test_confirmation_is_frozen() -> None:
    c = confirmation()
    with pytest.raises(ValueError):
        c.tenant_id = "other"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_content_fingerprint_is_deterministic_across_runs() -> None:
    rv = registration_view()
    a = validate_confirmation(confirmation(), rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    b = validate_confirmation(confirmation(), rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    assert isinstance(a, Accepted) and isinstance(b, Accepted)
    assert a.content_fingerprint == b.content_fingerprint


def test_content_fingerprint_changes_when_confirmed_at_changes() -> None:
    """confirmed_at is part of the content — a changed claim is a different
    fingerprint (so it is a conflicting, not duplicate, replay)."""
    rv = registration_view()
    a = validate_confirmation(confirmation(), rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    b = validate_confirmation(
        confirmation(confirmed_at=SERVER_RECEIVED_AT - timedelta(minutes=5)),
        rv,
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(a, Accepted) and isinstance(b, Accepted)
    assert a.content_fingerprint != b.content_fingerprint
