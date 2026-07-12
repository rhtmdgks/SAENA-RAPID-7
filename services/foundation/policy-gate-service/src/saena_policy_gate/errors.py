"""Exception hierarchy for `saena_policy_gate`.

Follows the same `saena.<category>.<reason>` `error_code` + structured,
log-safe `context` dict shape as `saena_domain.identity.errors` /
`saena_domain.persistence.errors` (ADR-0015 canonical error model) so the
RFC 9457 problem-detail mapper (`saena_policy_gate.problem`) can reuse these
verbatim as `error_code` values.

Fail-closed doctrine (ADR-0015 `policy_denied` category, `security-model.md`
"policy-gate = fail-closed": gate 장애 시 승인·실행 불가 — fail-open 금지):
`GateUnavailableError` is the ONE exception this module reserves for "the
policy engine itself could not render a decision" (rule-store failure,
evaluation exception, timeout) — it is a `PolicyDenyError` subclass, not a
distinct HTTP-5xx-style failure, precisely because a gate malfunction MUST
still resolve to a `deny` decision, never to an unhandled 500 that a caller
could misinterpret as "gate did not answer, so proceed". `error_code =
"saena.policy_denied.gate_unavailable"`, `retryable=False` (ADR-0015 table:
`policy_denied` category default is non-retryable; a fail-closed deny is not
something a client should blindly retry — the caller must intervene, e.g.
alert on-call, before the gate is healthy again).
"""

from __future__ import annotations

from typing import Any


class PolicyGateError(Exception):
    """Base class for every error raised by `saena_policy_gate`.

    Attributes:
        error_code: `saena.<category>.<reason>` taxonomy string (ADR-0015),
            reusable verbatim as a `ProblemDetail.error_code`.
        retryable: ADR-0015 `retryable` extension field default for this
            error's category — individual raise sites never override it,
            keeping the taxonomy's per-category default a single source of
            truth (see `saena_policy_gate.problem` for how this becomes the
            RFC 9457 response field).
        context: structured, log-safe data describing the violation. Never
            contains customer source, secrets, or PII (ADR-0015 Constraints
            — `detail`/`summary` fields forbid raw payload echoing).
    """

    error_code: str = "saena.internal.unexpected"
    retryable: bool = False
    http_status: int = 500

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class PolicyDenyError(PolicyGateError):
    """Base class for every `policy_denied` (ADR-0015 category) outcome.

    Raised for an ordinary default-deny rule-engine verdict (no matching
    allow rule) as well as for the fail-closed gate-malfunction case
    (`GateUnavailableError`, below) — both are `policy_denied`, distinguished
    by `error_code`/`reason` for callers/audit consumers that need to tell
    "the policy said no" apart from "the policy could not be evaluated".
    """

    error_code = "saena.policy_denied.rule_denied"
    retryable = False
    http_status = 403


class GateUnavailableError(PolicyDenyError):
    """Fail-closed: the policy engine could not render a decision at all.

    ADR-0015: "`saena.policy_denied.gate_unavailable`을 fail-closed 케이스로
    포함 — 게이트 자체 장애 시에도 요청을 승인이 아닌 거부로 처리(fail-closed)".
    `security-model.md`: "policy-gate = fail-closed: gate 장애 시 승인·실행
    불가 (fail-open 금지)". Raised by `saena_policy_gate.engine.PolicyEngine`
    whenever evaluation itself fails (broken rule store, unexpected
    exception, timeout) — never propagated as a bare 500; every route
    catches evaluation failures and re-raises/maps to this type so the HTTP
    response is always a `deny`, never an ambiguous server error a client
    might treat as "try again and maybe it'll allow this time".
    """

    error_code = "saena.policy_denied.gate_unavailable"
    retryable = False
    http_status = 503


class ValidationError(PolicyGateError):
    """Request/contract shape violation (ADR-0015 `validation` category)."""

    error_code = "saena.validation.schema_mismatch"
    retryable = False
    http_status = 400


class DecisionConflictError(PolicyGateError):
    """A decision_key replay carried a DIFFERENT decision than the one
    already on record (ADR-0015 `conflict` category) — mirrors
    `saena_domain.persistence.errors.DecisionConflictError` at the
    services layer, surfaced as a 409 rather than a bare exception.
    """

    error_code = "saena.conflict.decision_conflict"
    retryable = False
    http_status = 409


class TenantHeaderError(PolicyGateError):
    """`X-Saena-Tenant-Id` header missing/mismatched against the pod's
    `SAENA_TENANT_ID` env var (ADR-0014, same reconciliation contract as
    `saena_domain.identity.http.reconcile_tenant`) — `auth` category
    (ADR-0015), mapped to HTTP 403, never silently ignored or 200-ed
    (ADR-0014 Constraints:64).
    """

    error_code = "saena.auth.tenant_mismatch"
    retryable = False
    http_status = 403


__all__ = [
    "DecisionConflictError",
    "GateUnavailableError",
    "PolicyDenyError",
    "PolicyGateError",
    "TenantHeaderError",
    "ValidationError",
]
