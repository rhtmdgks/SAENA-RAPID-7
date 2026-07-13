"""Exception hierarchy for `saena_citation_intelligence` (w4-05).

Follows the exact same shape as `saena_vector_store.errors` /
`saena_site_discovery.errors`: every exception carries a `saena.<category>.
<reason>` `error_code` (ADR-0015 taxonomy) and a structured, log-safe
`.context` dict. This package is intentionally NOT a dependency of
`saena_domain` (exclusive write path is
`services/intelligence/citation-intelligence-service/**` only, no root
workspace registration yet — see this package's `pyproject.toml` NOTE), so
this is a local, small re-derivation of that shared convention rather than an
import of it, keeping this package fully self-contained at the error-model
layer (it DOES depend on `saena-domain` for `EnvelopeFactory`/`audit.
canonical`, per the task brief — only the error hierarchy itself is
re-derived, mirroring `saena_vector_store.errors`'s own stated rationale).
"""

from __future__ import annotations

from typing import Any


class CitationIntelligenceError(Exception):
    """Base class for every error raised by `saena_citation_intelligence`."""

    error_code: str = "saena.citation_intelligence.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class UrlNormalizationError(CitationIntelligenceError):
    """A citation URL could not be normalized into the `uri_ref` contract
    shape (`^[a-z0-9+.-]+://[^?#]+$`,
    `packages/contracts/json-schema/common/identifiers/v1/identifiers.schema.json`).

    Raised for: empty/whitespace-only input, a URL with no scheme or no
    host, a scheme this module does not recognize as safe to normalize, or a
    hostname that fails IDN/punycode (`str.encode("idna")`) conversion.
    Never silently coerced to a best-guess value — a citation this module
    cannot normalize deterministically is rejected outright (fail closed),
    matching this package's overall "never fabricate/guess" discipline.
    """

    error_code = "saena.validation.citation_url_invalid"


class OwnershipClassificationError(CitationIntelligenceError):
    """The rule-based + calibrated-prior ownership classifier could not
    reach a decision for a normalized citation (e.g. malformed
    `tenant_owned_domains`/`competitor_domains` input to the classifier).

    This is distinct from a *low-confidence* classification (which is a
    normal, valid `OwnershipDecision` outcome carrying
    `OwnershipClass.THIRD_PARTY` + a low `confidence` — see
    `ownership.py`) — this error means the classifier's OWN inputs were
    invalid, not that the citation was ambiguous.
    """

    error_code = "saena.validation.ownership_inputs_invalid"


class CrossTenantCitationError(CitationIntelligenceError):
    """A caller attempted to classify/normalize/emit a citation record under
    a `tenant_id` different from the one the surrounding call was scoped to
    (fail closed — mirrors `saena_site_discovery.errors.
    CrossTenantObservationError` / `saena_vector_store.errors.
    TenantIsolationError`'s cross-tenant gating discipline: cross-tenant
    access is a security event, never a silent no-op or a bare "not
    found").
    """

    error_code = "saena.auth.cross_tenant_denied"


class EngineNotPermittedError(CitationIntelligenceError):
    """`engine_id` is outside the v1 closed enum (`chatgpt-search` only).

    CLAUDE.md "Engine scope (v1)": Target = ChatGPT Search only; Google AI
    Overviews / Google AI Mode / Gemini are disabled — optimize/observe/
    claim forbidden for all three. This is this package's OWN guard (fires
    before any `saena_domain.events.EnvelopeFactory` call, so a disallowed
    engine never even reaches envelope construction) — distinct from, and
    strictly earlier than, `saena_domain.events.errors.
    EngineNotPermittedError`/`EngineIdRequiredError`, which the factory
    itself would also raise for the same input.
    """

    error_code = "saena.policy_denied.engine_not_permitted"


__all__ = [
    "CitationIntelligenceError",
    "CrossTenantCitationError",
    "EngineNotPermittedError",
    "OwnershipClassificationError",
    "UrlNormalizationError",
]
