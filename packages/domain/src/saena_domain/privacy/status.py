"""``de_identification_status`` transition rules (ADR-0013 AggregateContext).

The AggregateContext envelope requires a ``de_identification_status`` field
with enum values ``k_anonymized | suppressed | pending_review`` (ADR-0013
§Current decision table). The schema enum alone does not encode *which*
transitions between those states are legal — that is a domain rule this
module owns, and it is intentionally coupled to the k-anonymity gate
(:mod:`saena_domain.privacy.gate`): a record may only become
``k_anonymized`` when the gate has actually passed.

Reuses the generated ``DeIdentificationStatus`` enum from
``saena_schemas.envelope.event_envelope_v1`` (ADR-0011 SSOT split — domain
code consumes the codegen artifact rather than redeclaring the enum).
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_schemas.envelope.event_envelope_v1 import DeIdentificationStatus

from saena_domain.privacy.gate import GateDecision, KAnonymityGateResult

#: Legal (from_status, to_status) pairs. Self-transitions are not included —
#: they are neither required by ADR-0013 nor exercised by the publish-side
#: gate, and omitting them keeps the transition table an explicit allowlist.
_ALLOWED_TRANSITIONS: frozenset[tuple[DeIdentificationStatus, DeIdentificationStatus]] = frozenset(
    {
        (DeIdentificationStatus.pending_review, DeIdentificationStatus.k_anonymized),
        (DeIdentificationStatus.pending_review, DeIdentificationStatus.suppressed),
    }
)


class InvalidDeIdentificationTransitionError(ValueError):
    """Raised when a requested status transition is not in the allowlist."""

    def __init__(
        self, from_status: DeIdentificationStatus, to_status: DeIdentificationStatus
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"invalid de_identification_status transition: {from_status.value} -> {to_status.value}"
        )


class GateRequiredForKAnonymizedError(ValueError):
    """Raised when transitioning to ``k_anonymized`` without a passing gate result."""

    def __init__(self) -> None:
        super().__init__(
            "transition to k_anonymized requires a passing KAnonymityGateResult "
            "(ADR-0013 k-anonymity runtime gate)"
        )


@dataclass(frozen=True, slots=True)
class DeIdentificationTransition:
    """Immutable record of an applied status transition."""

    from_status: DeIdentificationStatus
    to_status: DeIdentificationStatus


def transition(
    from_status: DeIdentificationStatus,
    to_status: DeIdentificationStatus,
    *,
    gate_result: KAnonymityGateResult | None = None,
) -> DeIdentificationTransition:
    """Apply and validate a ``de_identification_status`` transition.

    Args:
        from_status: current status.
        to_status: requested status.
        gate_result: required when ``to_status`` is ``k_anonymized`` — must
            be a :class:`KAnonymityGateResult` with
            ``decision is GateDecision.ALLOWED``. Ignored for other target
            statuses (a manual suppression, for example, does not need a
            gate evaluation at all).

    Returns:
        A :class:`DeIdentificationTransition` record of the applied change.

    Raises:
        InvalidDeIdentificationTransitionError: if ``(from_status, to_status)``
            is not in the allowlist (e.g. ``k_anonymized`` -> anything,
            ``suppressed`` -> anything, or any self-transition).
        GateRequiredForKAnonymizedError: if ``to_status`` is ``k_anonymized``
            and ``gate_result`` is missing or its decision is
            ``GateDecision.SUPPRESSED``.
    """
    if (from_status, to_status) not in _ALLOWED_TRANSITIONS:
        raise InvalidDeIdentificationTransitionError(from_status, to_status)

    if to_status is DeIdentificationStatus.k_anonymized and (
        gate_result is None or gate_result.decision is not GateDecision.ALLOWED
    ):
        raise GateRequiredForKAnonymizedError()

    return DeIdentificationTransition(from_status=from_status, to_status=to_status)
