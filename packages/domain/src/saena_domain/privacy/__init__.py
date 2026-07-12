"""saena_domain.privacy — AggregateContext k-anonymity runtime gate (W2A).

Implements the publish-side runtime gate mandated by ADR-0013 ("k-anonymity
게이트의 스키마 한계"): ``cohort_size >= privacy_threshold`` cannot be
expressed in JSON Schema 2020-12, so the AggregateContext envelope schema
(``packages/contracts/json-schema/envelope/event-envelope/v1``, read-only
from this package) only constrains field types/minima and this module
enforces the relational invariant plus ``de_identification_status``
transition rules at application level. See also ADR-0006 rev.2 (3-context
envelope model that introduced AggregateContext as the cross-tenant,
de-identified Strategy Card publish path).

Public API:

- :class:`saena_domain.privacy.gate.KAnonymityGate` /
  :class:`saena_domain.privacy.gate.KAnonymityGateResult` /
  :class:`saena_domain.privacy.gate.GateDecision`
- :func:`saena_domain.privacy.status.transition` and its error types
- :func:`saena_domain.privacy.guard.guard_aggregate_publish` and its error
  types
"""

from __future__ import annotations

from saena_domain.privacy.gate import GateDecision, KAnonymityGate, KAnonymityGateResult
from saena_domain.privacy.guard import (
    AggregateEnvelopeLike,
    ForbiddenIdentifierPresentError,
    NotPublishableError,
    PrivacyGuardError,
    SuppressedEventError,
    WrongContextTypeError,
    guard_aggregate_publish,
)
from saena_domain.privacy.status import (
    DeIdentificationTransition,
    GateRequiredForKAnonymizedError,
    InvalidDeIdentificationTransitionError,
    transition,
)

__all__ = [
    "AggregateEnvelopeLike",
    "DeIdentificationTransition",
    "ForbiddenIdentifierPresentError",
    "GateDecision",
    "GateRequiredForKAnonymizedError",
    "InvalidDeIdentificationTransitionError",
    "KAnonymityGate",
    "KAnonymityGateResult",
    "NotPublishableError",
    "PrivacyGuardError",
    "SuppressedEventError",
    "WrongContextTypeError",
    "guard_aggregate_publish",
    "transition",
]
