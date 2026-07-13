"""The trusted 7-day measurement clock — started ONLY by an Accepted confirmation (w5-03).

Source specification references (READ-ONLY basis for this module):
- docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md §7.3:483 — "고객
  배포가 Day 2 이후로 늦어지면 7일 외부 성과 clock은 시작하지 않는다. 이는 제품
  약점이 아니라 외부 신호의 인과성을 지키기 위한 계약 조건이다." The Day-2 rule is
  implemented verbatim: if the deployment's server-observed receive time is
  later than ``registration.approved_at + max_deploy_delay_days`` (default 2),
  the clock does NOT start and the verdict is ``Undetermined(deployment_late)``.
- docs/architecture/wave5-plan.md §deliverable 2 — ``deployment.confirmed.v1``
  is the "Sole clock-start authority"; H6 — "7-day timer mechanism: Temporal
  durable timer + time-skipping tests". This module is the PURE domain half:
  it computes the window instant-arithmetically; the durable Temporal timer
  (w5-14) drives real time off this window's anchor/end.

## Structural clock-start invariant

There is NO public constructor, factory, or function in this module that starts
a window from a bare timestamp, a patch-creation time, a PR-creation time, a
merge time, or an "expected deploy" time. ``MeasurementWindow`` is guarded
against accidental/bare-timestamp construction: its ``__init__`` requires a
private token held only by ``start_measurement_window``, so the only supported
way to obtain a window is via an ``Accepted`` deployment confirmation. This is
a misuse guard, not a cryptographic one — in-process Python can always bypass
it (``model_construct``, ``object.__new__``, importing the module-private
token). The authenticity of a window is therefore established by the
confirmation record and the evidence bundle it links to, not by object
identity; the guard exists to make every honest code path go through
validation, and its removal is pinned by the structural test in
``tests/unit/domain_measurement_clock/test_clock.py``.

## Timezone / DST correctness by construction

The anchor is ``Accepted.server_received_at`` (already guaranteed UTC-aware by
``validate_confirmation``'s naive-datetime guard). The window end is
``anchor + timedelta(days=window_days)`` — a fixed *duration* added to an
absolute instant. Because the arithmetic is on aware ``datetime`` instants (not
on wall-clock calendar fields), the same physical instant expressed in any
timezone offset yields the identical window end instant — DST/timezone-proof by
construction (pinned by a property test over random tz offsets of one instant).
This module additionally rejects a naive anchor as a defence-in-depth belt to
``validate_confirmation``'s suspenders.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from saena_domain.measurement.confirmation import Accepted, Duplicate, RegistrationView

#: Private construction token. ``MeasurementWindow(...)`` raises unless
#: ``start_measurement_window`` (the intended sole holder) passes it. This is a
#: misuse guard against accidental/bare-timestamp construction — a determined
#: in-process caller can still import it or sidestep ``__init__`` entirely
#: (``model_construct``); window authenticity rests on the confirmation record,
#: not on this token (see module docstring).
_CONSTRUCT_TOKEN = object()


class ClockStartReason(str, Enum):
    """Typed reason a clock start did NOT happen (wave5-plan.md H7 enum v1)."""

    #: Deployment confirmed later than the Day-2 deadline (§7.3:483). The 7-day
    #: external-performance clock is deliberately not started — a causality
    #: contract condition, not a product defect.
    DEPLOYMENT_LATE = "deployment_late"


class MeasurementPolicy(BaseModel):
    """Window/deadline policy. Defaults encode the Algorithm §7.3 operating table.

    - ``window_days`` = 7: the fixed external-performance measurement window.
    - ``max_deploy_delay_days`` = 2: the Day-2 deadline — deployment must be
      confirmed by ``registration.approved_at + max_deploy_delay_days`` or the
      clock does not start (§7.3:483).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_days: int = Field(default=7, gt=0)
    max_deploy_delay_days: int = Field(default=2, ge=0)


class Undetermined(BaseModel):
    """Terminal verdict: the clock did NOT start; downstream is UNDETERMINED.

    Carries a typed ``reason``. An ``Undetermined`` never yields a window — any
    downstream verdict computed against it is UNDETERMINED semantics (never a
    default PASS/FAIL).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: ClockStartReason


class MeasurementWindow(BaseModel):
    """A started 7-day measurement window, built via ``start_measurement_window``.

    ``anchor`` is the deployment's ``server_received_at`` (trusted, UTC-aware).
    ``end`` is ``anchor + timedelta(days=window_days)``. The window is bound to
    the specific accepted confirmation's ``idempotency_key`` and content
    fingerprint so a duplicate confirmation resolves to the SAME window (never a
    restart) and a conflicting one is a fail-closed error at the boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    anchor: datetime
    end: datetime
    window_days: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1)
    content_fingerprint: str = Field(min_length=1)

    def __init__(self, *args: object, **kwargs: object) -> None:
        # Misuse guard: refuse construction unless the private token is
        # presented. ``start_measurement_window`` is the intended sole holder,
        # keeping honest code paths on the validated route (bypassable
        # in-process — see module docstring on window authenticity).
        if kwargs.pop("_token", None) is not _CONSTRUCT_TOKEN:
            raise TypeError(
                "MeasurementWindow cannot be constructed directly — a window "
                "starts ONLY from an Accepted deployment confirmation via "
                "start_measurement_window(); there is no bare-timestamp path"
            )
        super().__init__(*args, **kwargs)

    def window_complete(self, at: datetime) -> bool:
        """True iff instant ``at`` is at or after the window ``end``.

        A naive ``at`` is rejected (a naive instant cannot be compared against
        the UTC-aware ``end`` without an implicit-timezone assumption). An
        incomplete window (``at < end``) is False → UNDETERMINED semantics
        downstream: a verdict may not be finalized before the window closes.
        """
        if _is_naive(at):
            raise ValueError("window_complete(at) requires a timezone-aware datetime")
        return at >= self.end


ClockStartVerdict = MeasurementWindow | Undetermined


class ConflictingConfirmationError(Exception):
    """Raised when a confirmation conflicts with the window's bound confirmation.

    Fail-closed: a confirmation carrying the same idempotency key but a
    DIFFERENT content fingerprint than the window's anchoring confirmation is
    never silently resolved to either window — it is an error the caller must
    handle. Carries the idempotency key ONLY (non-leaking, mirrors
    ``saena_domain.experiment.errors`` redaction discipline).
    """

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(
            f"deployment confirmation for idempotency_key {idempotency_key!r} "
            "conflicts with the window's anchoring confirmation (same key, "
            "different content) — fail-closed, no arbitrary winner"
        )


def _is_naive(value: datetime) -> bool:
    return value.tzinfo is None or value.tzinfo.utcoffset(value) is None


def _day2_deadline(registration_view: RegistrationView, policy: MeasurementPolicy) -> datetime:
    """The Day-2 deadline: ``approved_at + max_deploy_delay_days`` (§7.3:483)."""
    return registration_view.approved_at + timedelta(days=policy.max_deploy_delay_days)


def start_measurement_window(
    accepted_confirmation: Accepted,
    registration_view: RegistrationView,
    policy: MeasurementPolicy | None = None,
) -> ClockStartVerdict:
    """Start the 7-day window from an ``Accepted`` confirmation — the ONLY entry.

    - The anchor is ``accepted_confirmation.server_received_at`` (trusted).
    - If the anchor is later than the Day-2 deadline (``approved_at +
      max_deploy_delay_days``), the clock does NOT start:
      ``Undetermined(deployment_late)`` (§7.3:483).
    - Otherwise a ``MeasurementWindow`` with ``end = anchor +
      window_days`` is returned.

    The function accepts ONLY an ``Accepted`` (structurally — the type is the
    key). There is no overload taking a bare timestamp. A naive anchor is
    rejected defensively (``validate_confirmation`` already guarantees aware,
    but this module does not trust its caller to have used it).

    ``registration_view`` must be the SAME registration the confirmation was
    accepted against — the accepted verdict embeds its own ``registration_view``
    and we assert consistency so a caller cannot pair an acceptance with a
    different registration's approval time to move the Day-2 deadline.
    """
    if not isinstance(accepted_confirmation, Accepted):  # pragma: no cover - typing belt
        raise TypeError(
            "start_measurement_window requires an Accepted confirmation — the "
            "clock never starts from any other value"
        )
    if accepted_confirmation.registration_view != registration_view:
        raise ValueError(
            "registration_view does not match the one the confirmation was "
            "accepted against — refusing to re-anchor the Day-2 deadline"
        )

    policy = policy or MeasurementPolicy()
    anchor = accepted_confirmation.server_received_at
    if _is_naive(anchor):  # pragma: no cover - validate_confirmation guarantees aware
        raise ValueError("accepted_confirmation.server_received_at must be timezone-aware")

    if anchor > _day2_deadline(registration_view, policy):
        return Undetermined(reason=ClockStartReason.DEPLOYMENT_LATE)

    return MeasurementWindow(
        anchor=anchor,
        end=anchor + timedelta(days=policy.window_days),
        window_days=policy.window_days,
        idempotency_key=accepted_confirmation.confirmation.idempotency_key,
        content_fingerprint=accepted_confirmation.content_fingerprint,
        _token=_CONSTRUCT_TOKEN,
    )


def resolve_duplicate_window(
    existing_window: MeasurementWindow,
    duplicate: Duplicate,
) -> MeasurementWindow:
    """A duplicate confirmation resolves to the SAME window (idempotent, no restart).

    Given the ``Duplicate`` verdict from ``validate_confirmation`` (same key,
    byte-identical content) and the window already started for that key, this
    returns the EXISTING window unchanged when the duplicate's fingerprint and
    key match it. If they do not match, it raises ``ConflictingConfirmationError``
    — fail-closed, never a restart, never an arbitrary winner. (A true
    conflicting replay is already rejected at validation time; this is the
    belt-and-suspenders guard for a caller pairing mismatched objects.)
    """
    accepted = duplicate.accepted
    if (
        accepted.confirmation.idempotency_key != existing_window.idempotency_key
        or accepted.content_fingerprint != existing_window.content_fingerprint
    ):
        raise ConflictingConfirmationError(existing_window.idempotency_key)
    return existing_window
