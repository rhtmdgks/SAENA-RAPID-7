"""Publish-side runtime gate for AggregateContext envelopes (ADR-0013 W2A).

ADR-0013 mandates a runtime gate at publish time because
``cohort_size >= privacy_threshold`` cannot be expressed in JSON Schema
2020-12 (see :mod:`saena_domain.privacy.gate`). :func:`guard_aggregate_publish`
is that gate's entry point for the publish path: it accepts an
AggregateContext envelope instance — either the generated pydantic model
(``saena_schemas.envelope.event_envelope_v1.AggregateContextEnvelope``) or a
plain ``dict`` shaped like one — and either returns normally (publish may
proceed) or raises a :class:`PrivacyGuardError` subclass (publish MUST be
blocked).

Structural checks enforced here, beyond the k-anonymity relation itself:

- ``de_identification_status`` consistency: ``k_anonymized`` requires a
  passing gate; ``suppressed`` is never publishable regardless of the gate
  outcome (an operator-suppressed record must stay suppressed even if the
  cohort numbers would otherwise pass); ``pending_review`` is never
  publishable (ADR-0013 AggregateContext is for material that has already
  cleared de-identification, not material awaiting a decision).
- ``tenant_id`` / ``run_id`` must be structurally absent (ADR-0013:
  AggregateContext forbids these properties outright — "forbidden" means
  the property cannot exist, not merely be empty/None). A dict that
  contains either key at all — even with a falsy value — is rejected,
  matching the schema's ``not: {anyOf: [{required: [tenant_id]}, ...]}``
  semantics (`packages/contracts/json-schema/envelope/event-envelope/v1`).
- ``lineage_audit_ref`` must be present and non-empty. Per ADR-0013 this
  value is an **opaque** audit-ledger reference: this module never parses,
  decodes, or interprets its contents. Read access to the underlying
  audit-ledger record it points to is restricted to the audit role — that
  access control is enforced by the audit-ledger service's RBAC layer, not
  by this function (this function only checks the envelope-local
  string is present, which is a structural precondition, not an access
  grant).

This function does not publish anything itself — it is a precondition
check meant to be called immediately before a producer hands an
AggregateContext envelope to the transport layer.
"""

from __future__ import annotations

from typing import Any

from saena_schemas.envelope.event_envelope_v1 import (
    AggregateContextEnvelope,
    DeIdentificationStatus,
)

from saena_domain.privacy.gate import GateDecision, KAnonymityGate

AggregateEnvelopeLike = AggregateContextEnvelope | dict[str, Any]

#: ADR-0013: AggregateContext forbids these properties outright.
_FORBIDDEN_KEYS = ("tenant_id", "run_id")

#: Required for the structural checks this guard performs. Absence of any
#: of these is a caller error (malformed input), not a privacy verdict —
#: it is reported as ValueError, distinct from the PrivacyGuardError family.
_REQUIRED_KEYS = (
    "cohort_size",
    "privacy_threshold",
    "de_identification_status",
    "lineage_audit_ref",
)


class PrivacyGuardError(Exception):
    """Base class for publish-blocking privacy guard failures."""


class SuppressedEventError(PrivacyGuardError):
    """Raised when the envelope must never be published.

    Covers both a gate-failed cohort (``cohort_size < privacy_threshold``)
    and a ``de_identification_status`` that is ``suppressed`` outright —
    either condition means the envelope must never reach the transport
    layer, regardless of the other's outcome.
    """


class NotPublishableError(PrivacyGuardError):
    """Raised for a structurally-valid envelope that is not yet publishable.

    Distinct from :class:`SuppressedEventError`: ``pending_review`` is not
    a rejection verdict, it is "not decided yet" — the caller should retry
    once the record has transitioned to ``k_anonymized`` (or been
    suppressed, in which case :class:`SuppressedEventError` applies).
    """


class ForbiddenIdentifierPresentError(PrivacyGuardError):
    """Raised when ``tenant_id`` or ``run_id`` is structurally present.

    ADR-0013: these properties are forbidden outright in AggregateContext,
    not merely optional-absent. Presence of the key at all — independent of
    its value — is the violation.
    """


def _as_mapping(envelope: AggregateEnvelopeLike) -> dict[str, Any]:
    if isinstance(envelope, AggregateContextEnvelope):
        # The generated model's own `extra="forbid"` config already makes
        # tenant_id/run_id structurally impossible to carry through
        # model_validate, so a model instance can only ever fail the
        # lineage/status/gate checks below, never the forbidden-key check.
        return envelope.model_dump(mode="python")
    if isinstance(envelope, dict):
        return envelope
    raise TypeError(
        f"envelope must be an AggregateContextEnvelope or dict, got {type(envelope).__name__}"
    )


def _status_of(raw_status: Any) -> DeIdentificationStatus:
    if isinstance(raw_status, DeIdentificationStatus):
        return raw_status
    if isinstance(raw_status, str):
        try:
            return DeIdentificationStatus(raw_status)
        except ValueError as exc:
            raise ValueError(f"unknown de_identification_status: {raw_status!r}") from exc
    raise TypeError(
        "de_identification_status must be a str or DeIdentificationStatus, got "
        f"{type(raw_status).__name__}"
    )


def guard_aggregate_publish(envelope: AggregateEnvelopeLike) -> None:
    """Enforce the AggregateContext publish-side runtime gate (ADR-0013 W2A).

    Returns ``None`` on success (publish may proceed). Raises a
    :class:`PrivacyGuardError` subclass to block publish, or ``TypeError`` /
    ``ValueError`` for malformed input that isn't itself a privacy verdict
    (missing required keys, wrong types).
    """
    data = _as_mapping(envelope)

    for forbidden_key in _FORBIDDEN_KEYS:
        if forbidden_key in data:
            raise ForbiddenIdentifierPresentError(
                f"AggregateContext envelope must not carry {forbidden_key!r} "
                "(ADR-0013: property forbidden outright, not merely absent-when-empty)"
            )

    missing = [key for key in _REQUIRED_KEYS if key not in data]
    if missing:
        raise ValueError(f"AggregateContext envelope missing required field(s): {missing}")

    lineage_audit_ref = data["lineage_audit_ref"]
    if not isinstance(lineage_audit_ref, str) or not lineage_audit_ref:
        raise ValueError("lineage_audit_ref must be a non-empty string")

    status = _status_of(data["de_identification_status"])

    if status is DeIdentificationStatus.suppressed:
        raise SuppressedEventError("de_identification_status is suppressed — never publishable")
    if status is DeIdentificationStatus.pending_review:
        raise NotPublishableError(
            "de_identification_status is pending_review — not yet publishable"
        )

    # status is k_anonymized from here: the gate itself is still the
    # authority on whether the cohort numbers actually support that claim
    # (a caller could hand us a k_anonymized status without ever having run
    # the gate — this is precisely the bypass ADR-0013's permanent
    # regression fixture documents, cf. cohort-below-threshold.json).
    gate_result = KAnonymityGate.evaluate(
        cohort_size=data["cohort_size"],
        privacy_threshold=data["privacy_threshold"],
    )
    if gate_result.decision is not GateDecision.ALLOWED:
        raise SuppressedEventError(
            "k-anonymity gate rejected publish: cohort_size "
            f"({gate_result.cohort_size}) < privacy_threshold "
            f"({gate_result.privacy_threshold})"
        )
