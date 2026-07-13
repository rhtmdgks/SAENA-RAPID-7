"""Errors raised by `saena_domain.experiment.ledger` (w4-09).

Redaction discipline (mirrors `saena_domain.audit.guard.ForbiddenAuditDataError`):
every error here carries an `experiment_id` ONLY — never the raw
registration content, arm/metric payloads, or hashes of anything beyond the
canonical experiment/prior-entry hash values already public in the ledger.
`experiment_id` is an identifier, not customer-proprietary content, so
echoing it back is safe and matches ADR-0015's audit error-footprint
principle (name the offending reference, not the offending data).
"""

from __future__ import annotations


class ExperimentDomainError(Exception):
    """Base class for all `saena_domain.experiment` errors."""


class ConflictError(ExperimentDomainError):
    """Raised when `experiment_id` is already registered with DIFFERENT content.

    Idempotency contract: the same `experiment_id` registered again with
    byte-identical content (same `canonical_hash`) is a no-op replay, not a
    conflict. This error fires only when the content actually differs and
    that difference is NOT an arm/metric-definition change (see
    `RejectedError` for that more specific, stricter case).
    """

    def __init__(self, experiment_id: str) -> None:
        self.experiment_id = experiment_id
        super().__init__(
            f"experiment_id {experiment_id!r} is already registered with different "
            "content — idempotent replay requires byte-identical content for the "
            "same experiment_id"
        )


class RejectedError(ExperimentDomainError):
    """Raised when a re-registration attempts to mutate `arms` or `metric_definitions`.

    Preregistration immutability (design §3.7.1-2; the precedent
    `run-context-experiment` schema's `registration_hash` field docstring:
    "사전등록 불변성") means an experiment's design — its arms and the metrics
    it declared it would measure — may never change after first
    registration. This is fail-closed and distinct from `ConflictError`: a
    changed `arms`/`metric_definitions` is always rejected, even if the
    caller intended it as a correction.
    """

    def __init__(self, experiment_id: str) -> None:
        self.experiment_id = experiment_id
        super().__init__(
            f"experiment_id {experiment_id!r} rejected: arms/metric_definitions may "
            "not be mutated after registration (preregistration immutability)"
        )
