"""Exception hierarchy for `saena_experiment_attribution.boundary` (w5-12).

Follows the exact same shape as `saena_domain.measurement.errors` /
`saena_citation_intelligence.errors`: every exception carries a
`saena.<category>.<reason>` `error_code` (ADR-0015 taxonomy) and a
structured, log-safe `.context` dict — never the raw payload/value that
triggered it.

## Uniform non-leaking error surface (deliverable #4)

`BoundaryLookupAbsent` is the ONE shape used for every cross-tenant lookup
miss and every "not found" outcome at this boundary. A caller presenting a
real `registration_hash` under the WRONG `tenant_id` and a caller presenting
a `registration_hash` that never existed at all receive the *identical*
exception type, message shape, and context keys — there is no oracle signal
(timing, distinguishing error subtype, or distinguishing field) that lets an
unauthorized caller tell "wrong tenant" apart from "no such record". This is
the boundary-layer resolution of the w5-18 `cross_tenant_replay` finding
(also see `tenancy.RegistrationLookup` docstring).
"""

from __future__ import annotations

from typing import Any


class BoundaryError(Exception):
    """Base class for every error raised by `saena_experiment_attribution.boundary`."""

    error_code: str = "saena.experiment_attribution.boundary.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class BoundaryLookupAbsent(BoundaryError):
    """Uniform "absent" result for every cross-tenant / not-found lookup at
    this boundary.

    Deliberately carries ONLY the fields the caller already supplied (never
    which tenant was "actually" expected, never a hint distinguishing
    "wrong tenant" from "never existed") — see module docstring. Callers
    that want a non-raising absent signal should prefer
    `tenancy.RegistrationLookup.lookup` returning `None`; this exception
    exists for call sites that need to raise (mirrors
    `saena_domain.measurement.errors.NotFoundError`'s non-leaking shape).
    """

    error_code = "saena.experiment_attribution.boundary.not_found"


class PayloadValidationError(BoundaryError):
    """An incoming envelope/payload failed schema or structural validation.

    Raised for: schema-invalid payload shape, payload-level tenant_id/run_id
    duplication (ADR-0014), missing required transport metadata. Never
    echoes the raw payload — only field names / a redacted reason.
    """

    error_code = "saena.validation.payload_invalid"


class TenantDuplicationError(PayloadValidationError):
    """The payload carried its own `tenant_id` (or `run_id`) in addition to
    the envelope's — a direct ADR-0014 violation (envelope `tenant_id` is
    the SOLE authority; payload duplication is forbidden, never silently
    ignored or silently preferred).
    """

    error_code = "saena.validation.payload_tenant_duplication"


class EngineNotPermittedError(BoundaryError):
    """`engine_id` is outside the v1 closed enum (`chatgpt-search` only).

    CLAUDE.md "Engine scope (v1)": Target = ChatGPT Search only; Google AI
    Overviews / Google AI Mode / Gemini are disabled — optimize/observe/
    claim forbidden for all three.
    """

    error_code = "saena.policy_denied.engine_not_permitted"


class PublishRefusedError(BoundaryError):
    """`OutcomePublisher` refused to publish — a fail-closed policy-gate
    obligation was not satisfied for a `b_verdict == "pass"` payload.

    Raised INSTEAD OF publishing a downgraded/partial payload — there is no
    code path that silently weakens a refused publish into some other
    verdict. `context["reasons"]` names every unmet condition (multiple
    conditions may be unmet simultaneously; all are reported, not just the
    first).
    """

    error_code = "saena.policy_denied.gate_unavailable"


class BasisDerivationError(BoundaryError):
    """An `evidence_basis_id` could not be deterministically derived from an
    observation artifact hash (e.g. the artifact hash itself was malformed).

    Never falls back to a caller-asserted string (w5-06 trust-boundary
    obligation) — a derivation failure is a hard refusal, not a silent
    substitution.
    """

    error_code = "saena.validation.basis_derivation_failed"


__all__ = [
    "BasisDerivationError",
    "BoundaryError",
    "BoundaryLookupAbsent",
    "EngineNotPermittedError",
    "PayloadValidationError",
    "PublishRefusedError",
    "TenantDuplicationError",
]
