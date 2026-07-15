"""Deployment-confirmation validation — the sole gate to a trusted clock start (w5-03).

Source specification references (READ-ONLY basis for this module):
- docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md §7.3:483 — "고객
  배포가 Day 2 이후로 늦어지면 7일 외부 성과 clock은 시작하지 않는다"; the Day-2
  rule itself lives in ``clock.py``, but validation here is the precondition
  that must pass before a clock start is even considered.
- docs/architecture/wave5-plan.md H5 (working assumption): the confirmer trust
  model is "signed external identity → policy-gate-first → direct signal;
  server receive-time anchor". This module encodes the *domain* half of that:
  identity binding, signed-confirmer verification via an injected verifier,
  and server-observed timestamp authority. Production confirmer identity/keys
  stay BLOCKED(human) (H5 BLOCKED column) — this module accepts an injected
  ``TrustVerifier`` and never embeds a key.
- wave5-plan.md E2: "``deployment.confirmed.v1`` is the ONLY clock start;
  identity/hash/target/confirmer/server-timestamp/idempotency/replay/backdate/
  cross-tenant validated".

## Fail-closed discipline

Every guard here is fail-closed: a missing verifier, a failed verification, an
unknown registration hash, an identity mismatch, a conflicting replay, or a
backdated/future timestamp all yield a ``Rejected`` (or, for a byte-identical
replay, a ``Duplicate`` no-op) — NEVER a default ``Accepted``. There is no code
path that accepts a confirmation that has not affirmatively passed every guard.

## Non-leaking rejections

``Rejected`` carries a typed ``reason_code`` and the ``idempotency_key`` /
``experiment_id`` references ONLY — never the raw confirmer identity payload,
signature bytes, or a diff of the mismatched fields (mirrors
``saena_domain.experiment.errors`` redaction discipline: name the offending
reference, not the offending data). In particular a cross-tenant replay is
reported as ``cross_tenant_replay`` without echoing which tenant was expected
vs. presented, so the rejection cannot be used as an identity oracle.

## Reuse, not reinvention

Byte-identical-content detection reuses ``saena_domain.audit.canonical`` (the
same JCS-style canonicalization the audit chain and the w4 registration ledger
are built on) — this module invents no new hashing rule (wave5-plan.md Binding
conventions: "Registration hash chain: reuse ``saena_domain.audit.canonical``").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saena_domain.audit.canonical import canonical_json, sha256_hex

_SHA256_PREFIX = "sha256:"


class RejectionReason(str, Enum):
    """Typed, code-level reason vocabulary (wave5-plan.md H7: "typed code-level
    enum v1"). Every rejection names exactly one reason; the set is closed and
    each value is non-leaking (an identifier of *why*, never the offending data).
    """

    #: Confirmation's tenant did not match the registered experiment view.
    #: Deliberately NOT distinguished from a run/project/site tenant-scope
    #: mismatch at the *value* level — the reason names the class of failure.
    CROSS_TENANT_REPLAY = "cross_tenant_replay"
    #: run_id / project / site (non-tenant identity fields) did not match.
    IDENTITY_MISMATCH = "identity_mismatch"
    #: Neither a deployed commit sha nor an immutable artifact hash was present.
    MISSING_DEPLOY_ARTIFACT = "missing_deploy_artifact"
    #: No deployment-target identity was present.
    MISSING_DEPLOYMENT_TARGET = "missing_deployment_target"
    #: No trust verifier was injected — fail-closed, never default-accept.
    UNTRUSTED_CONFIRMER = "untrusted_confirmer"
    #: A verifier was present but verification did not pass — fail-closed.
    CONFIRMER_VERIFICATION_FAILED = "confirmer_verification_failed"
    #: confirmed_at claim precedes registration creation/approval — backdated.
    BACKDATED_CONFIRMATION = "backdated_confirmation"
    #: confirmed_at claim is beyond server_received_at + allowed_skew — future.
    FUTURE_CONFIRMATION = "future_confirmation"
    #: idempotency key seen before with DIFFERENT content — fail-closed, no
    #: arbitrary winner.
    CONFLICTING_REPLAY = "conflicting_replay"
    #: registration_canonical_hash referenced an unknown/unregistered experiment.
    UNKNOWN_REGISTRATION = "unknown_registration"
    #: A naive (tz-unaware) datetime was supplied where UTC-aware is required.
    NAIVE_TIMESTAMP = "naive_timestamp"


@runtime_checkable
class TrustVerifier(Protocol):
    """Injected verifier for the signed external confirmer identity (H5).

    ``validate_confirmation`` calls ``verify(confirmation)`` and treats a
    truthy return as "confirmer trusted". The verifier is the ONLY place a
    confirmer becomes trusted — there is no fallback that trusts a confirmer
    without it. Production key material lives behind an implementation of this
    protocol (BLOCKED(human), H5); the domain never embeds a key.
    """

    def verify(self, confirmation: DeploymentConfirmation) -> bool:  # pragma: no cover - protocol
        ...


class RegistrationView(BaseModel):
    """Trusted, read-only projection of a pre-registered experiment.

    This is the authority the incoming (untrusted) ``DeploymentConfirmation``
    is bound against. It is NOT constructed from the confirmation — it is the
    registration record already anchored in the w4 ledger. ``approved_at`` and
    ``created_at`` are the trusted lower bounds a ``confirmed_at`` claim may not
    predate (backdate guard).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    site: str = Field(min_length=1)
    registration_canonical_hash: str = Field(min_length=1)
    created_at: datetime
    approved_at: datetime


class DeploymentConfirmation(BaseModel):
    """An UNTRUSTED external claim that a customer deployment happened.

    Every field here is attacker-influenceable and is validated before any
    trust is extended. ``confirmed_at`` is explicitly a *claim* — the trusted
    timestamp authority is ``server_received_at`` (a separate argument to
    ``validate_confirmation``), never this field. Either ``deployed_commit_sha``
    OR ``artifact_hash`` must be present (the deployed-artifact identity);
    ``deployment_target`` names WHERE it was deployed. ``confirmer_identity`` /
    ``confirmer_signature`` are consumed only by the injected ``TrustVerifier``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    site: str = Field(min_length=1)
    registration_canonical_hash: str = Field(min_length=1)
    deployment_target: str | None = Field(default=None, min_length=1)
    deployed_commit_sha: str | None = Field(default=None, min_length=1)
    artifact_hash: str | None = Field(default=None, min_length=1)
    confirmed_at: datetime
    idempotency_key: str = Field(min_length=1)
    confirmer_identity: str = Field(min_length=1)
    confirmer_signature: str = Field(min_length=1)

    @model_validator(mode="after")
    def _forbid_empty_after_strip(self) -> DeploymentConfirmation:
        # min_length=1 already forbids "" but not a whitespace-only string;
        # a whitespace-only deployment_target/commit sha is not an identity.
        for name in ("deployment_target", "deployed_commit_sha", "artifact_hash"):
            value = getattr(self, name)
            if value is not None and value.strip() == "":
                raise ValueError(f"{name} must not be whitespace-only")
        return self


class Accepted(BaseModel):
    """Terminal verdict: the confirmation passed EVERY guard.

    Carries the ``server_received_at`` anchor (the trusted timestamp) and the
    confirmation itself. ``start_measurement_window`` (clock.py) accepts ONLY
    this type — an ``Accepted`` is the sole structural key to a clock start.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmation: DeploymentConfirmation
    registration_view: RegistrationView
    server_received_at: datetime
    content_fingerprint: str = Field(min_length=1)


class Rejected(BaseModel):
    """Terminal verdict: fail-closed rejection with a typed, non-leaking reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason_code: RejectionReason
    idempotency_key: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)


class Duplicate(BaseModel):
    """Terminal verdict: idempotent no-op — same key, byte-identical content.

    Carries the ORIGINAL accepted verdict so callers observe the exact same
    window/anchor as the first time (no state change, no re-evaluation of a
    second acceptance).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: Accepted


#: A previously-accepted confirmation keyed by its idempotency key. The value
#: is the full ``Accepted`` verdict (which embeds the content fingerprint used
#: for byte-identical comparison). ``validate_confirmation`` treats this as
#: read-only prior state — it never mutates it (the caller persists a new
#: accepted verdict on the ``Accepted`` return, mirroring the ledger's
#: "returns a NEW state" contract).
PriorState = dict[str, Accepted]

ConfirmationVerdict = Accepted | Rejected | Duplicate


def _is_naive(value: datetime) -> bool:
    """True if ``value`` is timezone-naive (no ``tzinfo`` / no UTC offset)."""
    return value.tzinfo is None or value.tzinfo.utcoffset(value) is None


def _content_fingerprint(confirmation: DeploymentConfirmation) -> str:
    """Deterministic content fingerprint of a confirmation for idempotency.

    Reuses ``saena_domain.audit.canonical`` verbatim (JCS-style sorted-key
    compact JSON + SHA-256), the same rule the audit chain and registration
    ledger use. Two byte-identical confirmations fingerprint identically on
    every process/machine; any field difference → a different fingerprint.
    ``mode="json"`` renders datetimes deterministically (ISO-8601), so a
    ``confirmed_at`` change is a content change.
    """
    material = confirmation.model_dump(mode="json")
    return f"{_SHA256_PREFIX}{sha256_hex(canonical_json(material))}"


def _reject(reason: RejectionReason, confirmation: DeploymentConfirmation) -> Rejected:
    return Rejected(
        reason_code=reason,
        idempotency_key=confirmation.idempotency_key,
        experiment_id=confirmation.experiment_id,
    )


def validate_confirmation(
    confirmation: DeploymentConfirmation,
    registration_view: RegistrationView,
    server_received_at: datetime,
    trust_verifier: TrustVerifier | None,
    prior_state: PriorState,
    allowed_skew_seconds: int = 0,
) -> ConfirmationVerdict:
    """Validate an untrusted deployment confirmation. Fail-closed throughout.

    Returns exactly one of:

    - ``Duplicate`` — the ``idempotency_key`` was seen before AND the incoming
      content is byte-identical to the stored one: a no-op replay. The original
      ``Accepted`` verdict is returned unchanged (no state change).
    - ``Rejected`` — any guard failed (typed ``reason_code``). This includes a
      *conflicting* replay (same key, different content) which is
      ``conflicting_replay`` — never an arbitrary winner.
    - ``Accepted`` — every guard passed. Carries the ``server_received_at``
      anchor and the content fingerprint.

    Guard order is tenant-first (w5-04 precedent, critic #2 hardening): the
    identity binding runs BEFORE the idempotency lookup, so a foreign tenant's
    submission that happens to collide on an ``idempotency_key`` is rejected as
    a cross-tenant/identity failure — it can never surface another tenant's
    prior state as a ``conflicting_replay`` (DoS-shaped confusion) or as a
    ``Duplicate``. A byte-identical replay of an accepted confirmation still
    resolves to ``Duplicate`` (its identity fields match by definition of
    byte-identical) before any trust is re-extended. All guards are
    independent — each one's removal flips at least one test assertion
    (guard-mutation).

    ``server_received_at`` is the trusted timestamp authority; ``confirmed_at``
    on the payload is a claim only.
    """
    # --- Timezone discipline: naive datetimes are rejected up front. -------
    # A naive server_received_at cannot anchor a UTC window; a naive
    # confirmed_at claim cannot be safely compared. Fail-closed.
    if _is_naive(server_received_at) or _is_naive(confirmation.confirmed_at):
        return _reject(RejectionReason.NAIVE_TIMESTAMP, confirmation)

    # --- Identity binding (fail-closed, non-leaking; BEFORE idempotency). --
    # tenant mismatch is reported distinctly as cross_tenant_replay (the most
    # security-sensitive class) WITHOUT echoing the expected/presented tenant.
    # Running this before the idempotency lookup means an idempotency-key
    # collision from a different tenant/identity can never observe or disturb
    # another identity's prior state (critic #2 should-fix, tenant-first).
    if confirmation.tenant_id != registration_view.tenant_id:
        return _reject(RejectionReason.CROSS_TENANT_REPLAY, confirmation)
    if (
        confirmation.run_id != registration_view.run_id
        or confirmation.project != registration_view.project
        or confirmation.site != registration_view.site
        or confirmation.experiment_id != registration_view.experiment_id
    ):
        return _reject(RejectionReason.IDENTITY_MISMATCH, confirmation)

    # --- Idempotency (after identity, before trust extension). -------------
    # Same key + byte-identical content → Duplicate (return original accepted).
    # Same key + DIFFERENT content → conflicting_replay reject (fail-closed;
    # never pick an arbitrary winner, never re-accept).
    fingerprint = _content_fingerprint(confirmation)
    prior = prior_state.get(confirmation.idempotency_key)
    if prior is not None:
        if prior.content_fingerprint == fingerprint:
            return Duplicate(accepted=prior)
        return _reject(RejectionReason.CONFLICTING_REPLAY, confirmation)

    # --- Linkage: the confirmation must reference the registered hash. -----
    # Unknown / mismatched registration_canonical_hash → reject. This binds the
    # confirmation to a specific pre-registered experiment.
    if confirmation.registration_canonical_hash != registration_view.registration_canonical_hash:
        return _reject(RejectionReason.UNKNOWN_REGISTRATION, confirmation)

    # --- Deployed-artifact identity: commit sha OR immutable artifact hash. -
    if confirmation.deployed_commit_sha is None and confirmation.artifact_hash is None:
        return _reject(RejectionReason.MISSING_DEPLOY_ARTIFACT, confirmation)

    # --- Deployment-target identity required. ------------------------------
    if confirmation.deployment_target is None:
        return _reject(RejectionReason.MISSING_DEPLOYMENT_TARGET, confirmation)

    # --- Trusted confirmer: verifier absent OR verify() != True → reject. --
    # Fail-closed: there is NO branch that trusts a confirmer without a
    # LITERAL `True` from an injected verifier. Strict `is True` identity
    # (critic #2 should-fix): a sloppy/compromised verifier returning a merely
    # truthy value ('yes', 1, a non-empty object) is NOT trusted — truthiness
    # is not verification.
    if trust_verifier is None:
        return _reject(RejectionReason.UNTRUSTED_CONFIRMER, confirmation)
    verification_result = trust_verifier.verify(confirmation)
    if verification_result is not True:
        return _reject(RejectionReason.CONFIRMER_VERIFICATION_FAILED, confirmation)

    # --- Timestamp authority: server_received_at is trusted. ---------------
    # confirmed_at earlier than registration created/approved → backdated.
    # We anchor the lower bound at the EARLIER of created_at/approved_at so a
    # claim before the experiment could possibly have existed is rejected.
    earliest_valid = min(registration_view.created_at, registration_view.approved_at)
    if confirmation.confirmed_at < earliest_valid:
        return _reject(RejectionReason.BACKDATED_CONFIRMATION, confirmation)
    # confirmed_at beyond server_received_at + allowed_skew → future spoof.
    # A negative allowed-skew is nonsensical (it would reject valid
    # same-instant confirmations) and is rejected fail-closed at the boundary.
    if allowed_skew_seconds < 0:
        raise ValueError("allowed_skew_seconds must be non-negative")
    if confirmation.confirmed_at > server_received_at + timedelta(seconds=allowed_skew_seconds):
        return _reject(RejectionReason.FUTURE_CONFIRMATION, confirmation)

    return Accepted(
        confirmation=confirmation,
        registration_view=registration_view,
        server_received_at=server_received_at,
        content_fingerprint=fingerprint,
    )
