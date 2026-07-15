"""Pure measurement-workflow state-machine core — import-safe, unit-testable
WITHOUT a Temporal server (mirrors ``saena_orchestrator.workflow_logic``: pure
logic separated from the ``@workflow.defn`` shell so the deterministic decisions
are tested to ~100% off-server, and the shell is exercised under a real
time-skipping ``WorkflowEnvironment`` in the integration lane).

## Authority path (ADR-0003 pattern, wave5-plan.md Binding conventions)

"B-gate/clock authority path: Policy-Gate-first fail-closed → direct Temporal
signal; bus events notification-only". The ``deployment-confirmed`` **signal**
carries an ALREADY-VALIDATED ``Accepted`` confirmation reference — validation
(identity/hash/target/confirmer/timestamp/idempotency/replay) is the
service/policy-gate's job UPSTREAM (``saena_domain.measurement.confirmation.
validate_confirmation``, w5-03), NOT re-done here. This module RE-CHECKS only
the *structural* invariants defensively (defense-in-depth, ADR-0003 step 4):
that the payload is an ``Accepted``, that its embedded registration matches, and
that a second confirmation for the same window is either the identical one
(idempotent) or a conflict (fail-closed, first-wins) — it never re-runs trust
verification (no key material here; that stays BLOCKED(human), H5).

## What is PURE here vs. what is an ACTIVITY

The window derivation itself (``start_measurement_window``) is a domain call that
in production pairs with a ``registration_view`` lookup — nondeterministic-
adjacent — so it runs in an **activity** (``activities.derive_window``), not in
the workflow body. This module therefore does NOT call
``start_measurement_window``; it holds the pure *decision* logic around the
signal: structural acceptance, idempotency/conflict resolution, abort handling,
and the terminal outcome vocabulary. Every function here is deterministic and
free of ``datetime.now``/IO/randomness (Temporal determinism requirement).

## Fail-closed / never-silently-dropped discipline

- A duplicate deployment-confirmed signal (same idempotency key + identical
  content fingerprint) is idempotent: the timer is NOT restarted.
- A conflicting confirmation signal (same key, DIFFERENT content) is recorded as
  ``conflicting_replay`` and the ORIGINAL window continues (fail-closed, first
  wins) — never an arbitrary winner, never a restart.
- An abort is recorded as ``UNDETERMINED(aborted)`` — never silently dropped.
- A deployment confirmed after the Day-2 deadline yields
  ``UNDETERMINED(deployment_late)`` and the 7-day timer is NEVER started
  (§7.3:483, enforced by ``start_measurement_window`` in the activity; this
  module carries the resulting outcome vocabulary).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from saena_domain.measurement.clock import ClockStartReason
from saena_domain.measurement.confirmation import Accepted

# ---------------------------------------------------------------------------
# Signal names (single source; the workflow shell and the client both import
# these so a rename can never silently desync sender and receiver — same
# discipline as saena_orchestrator's APPROVE_SIGNAL_NAME constant).
# ---------------------------------------------------------------------------
DEPLOYMENT_CONFIRMED_SIGNAL = "deployment_confirmed"
PAUSE_OBSERVATION_SIGNAL = "pause_observation"
RESUME_OBSERVATION_SIGNAL = "resume"
ABORT_MEASUREMENT_SIGNAL = "abort_measurement"


class MeasurementOutcomeStatus(str, Enum):
    """Terminal disposition of a measurement workflow run.

    ``DECIDED`` is the ONLY status that carries a real collect-and-decide
    outcome reference (the window closed and the DiD/B-gate pipeline ran).
    Every other status is an ``UNDETERMINED`` variant with a typed reason —
    an UNDETERMINED run NEVER yields a PASS/FAIL success verdict (wave5-plan.md
    UNDETERMINED semantics: "missing evidence = not claimed").
    """

    #: Window closed normally; the collect-and-decide activity produced an
    #: outcome record reference. Only status that is NOT undetermined.
    DECIDED = "decided"
    #: The clock never started because the deployment was confirmed after the
    #: Day-2 deadline (§7.3:483). No timer was ever set.
    UNDETERMINED_DEPLOYMENT_LATE = "undetermined_deployment_late"
    #: An ``abort_measurement`` signal was received before the window closed.
    #: Recorded, never silently dropped.
    UNDETERMINED_ABORTED = "undetermined_aborted"


class SignalDisposition(str, Enum):
    """Result of applying one deployment-confirmed signal to the window state.

    Pure classification consumed by the workflow shell to decide whether to
    start the timer, no-op, or record a conflict. Never mutates anything.
    """

    #: First valid confirmation for this run — start the window/timer.
    START = "start"
    #: Same idempotency key + identical content fingerprint — idempotent no-op.
    #: The timer is NOT restarted (pinned by the duplicate-signal integration
    #: test).
    DUPLICATE = "duplicate"
    #: Same idempotency key, DIFFERENT content fingerprint — conflicting replay.
    #: Recorded; the ORIGINAL window continues (fail-closed, first wins).
    CONFLICTING_REPLAY = "conflicting_replay"
    #: Structurally invalid signal payload (not an Accepted, or registration
    #: mismatch) — refused, no state change.
    REFUSED_STRUCTURAL = "refused_structural"


@dataclass(frozen=True, slots=True)
class WindowBinding:
    """Immutable identity of the window a run is (or would be) bound to.

    Extracted from the FIRST accepted confirmation. Subsequent confirmations
    are classified against THIS binding (idempotent vs. conflicting) — the
    binding is never overwritten (first-wins). ``content_fingerprint`` /
    ``idempotency_key`` come from ``saena_domain.measurement.confirmation``
    (reused, not reinvented — the audit-canonical fingerprint).
    """

    idempotency_key: str
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class MeasurementOutcome:
    """Terminal outcome record REFERENCE returned by the workflow.

    This is a *reference*, not the full evidence bundle: it names the status,
    the typed reason (for UNDETERMINED variants), and — for a ``DECIDED`` run —
    the opaque ``outcome_ref`` the collect-and-decide activity produced (the
    actual DiD/B-gate/evidence-bundle payload lives behind that ref, owned by
    w5-13's pipeline; this workflow never inspects its internals).
    """

    status: MeasurementOutcomeStatus
    idempotency_key: str
    #: Opaque reference to the collect-and-decide result (DECIDED only), or
    #: None for UNDETERMINED variants.
    outcome_ref: str | None = None
    #: Typed reason string for UNDETERMINED variants (None for DECIDED).
    reason: str | None = None


def extract_binding(accepted: Accepted) -> WindowBinding:
    """Derive the immutable ``WindowBinding`` from an accepted confirmation.

    Pure. The binding keys off the confirmation's ``idempotency_key`` and the
    Accepted's ``content_fingerprint`` (the audit-canonical fingerprint the
    upstream validator already computed) — no new hashing rule.
    """
    return WindowBinding(
        idempotency_key=accepted.confirmation.idempotency_key,
        content_fingerprint=accepted.content_fingerprint,
    )


def classify_confirmation_signal(
    accepted_payload: object,
    existing_binding: WindowBinding | None,
    expected_registration_hash: str,
) -> SignalDisposition:
    """Classify an incoming deployment-confirmed signal payload. Pure.

    Defense-in-depth structural re-check (NOT trust re-verification):

    - The payload MUST be an ``Accepted`` (the signal contract carries an
      already-validated Accepted reference). Anything else → ``REFUSED_STRUCTURAL``.
    - The Accepted's embedded ``registration_view.registration_canonical_hash``
      MUST equal ``expected_registration_hash`` (the run's bound registration).
      A confirmation for a DIFFERENT registration is refused structurally — it
      can never re-anchor THIS run's window.
    - If no window is bound yet → ``START`` (first valid confirmation).
    - If a window is bound and the incoming fingerprint+key match it →
      ``DUPLICATE`` (idempotent; timer NOT restarted).
    - If the key matches but the fingerprint differs (or vice versa) →
      ``CONFLICTING_REPLAY`` (recorded; original window continues, first wins).

    This mirrors ``validate_confirmation``'s own idempotency/conflict split but
    at the WORKFLOW level over the (already-Accepted) payload — it is the
    replay-safe idempotency guarantee the durable timer relies on.
    """
    if not isinstance(accepted_payload, Accepted):
        return SignalDisposition.REFUSED_STRUCTURAL

    accepted = accepted_payload
    if accepted.registration_view.registration_canonical_hash != expected_registration_hash:
        return SignalDisposition.REFUSED_STRUCTURAL

    incoming = extract_binding(accepted)
    if existing_binding is None:
        return SignalDisposition.START

    if (
        incoming.idempotency_key == existing_binding.idempotency_key
        and incoming.content_fingerprint == existing_binding.content_fingerprint
    ):
        return SignalDisposition.DUPLICATE

    # Same key, different content — OR a different key colliding on this run:
    # either way the first binding wins and this is a fail-closed conflict.
    return SignalDisposition.CONFLICTING_REPLAY


def deployment_late_outcome(idempotency_key: str) -> MeasurementOutcome:
    """The terminal outcome when ``start_measurement_window`` returned
    ``Undetermined(deployment_late)`` — the clock never started (§7.3:483).
    Pure; carries the typed reason from ``ClockStartReason``.
    """
    return MeasurementOutcome(
        status=MeasurementOutcomeStatus.UNDETERMINED_DEPLOYMENT_LATE,
        idempotency_key=idempotency_key,
        reason=ClockStartReason.DEPLOYMENT_LATE.value,
    )


def aborted_outcome(idempotency_key: str) -> MeasurementOutcome:
    """The terminal outcome when an ``abort_measurement`` signal arrived before
    the window closed. Recorded as ``UNDETERMINED(aborted)`` — never silently
    dropped. Pure.
    """
    return MeasurementOutcome(
        status=MeasurementOutcomeStatus.UNDETERMINED_ABORTED,
        idempotency_key=idempotency_key,
        reason="aborted",
    )


def decided_outcome(idempotency_key: str, outcome_ref: str) -> MeasurementOutcome:
    """The terminal outcome when the window closed and the collect-and-decide
    activity produced ``outcome_ref``. Pure.
    """
    return MeasurementOutcome(
        status=MeasurementOutcomeStatus.DECIDED,
        idempotency_key=idempotency_key,
        outcome_ref=outcome_ref,
    )


__all__ = [
    "ABORT_MEASUREMENT_SIGNAL",
    "DEPLOYMENT_CONFIRMED_SIGNAL",
    "PAUSE_OBSERVATION_SIGNAL",
    "RESUME_OBSERVATION_SIGNAL",
    "MeasurementOutcome",
    "MeasurementOutcomeStatus",
    "SignalDisposition",
    "WindowBinding",
    "aborted_outcome",
    "classify_confirmation_signal",
    "decided_outcome",
    "deployment_late_outcome",
    "extract_binding",
]
