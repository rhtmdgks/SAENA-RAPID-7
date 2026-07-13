"""Engine guard — v1 closed `engine_id` enum enforcement for execution-domain jobs.

ADR-0013 §Current decision `engine_id`: closed enum `["chatgpt-search"]` (v1
single value). CLAUDE.md "Engine scope (v1)": Target = ChatGPT Search only;
Google AI Overviews / Google AI Mode / Gemini are disabled —
optimize/observe/claim forbidden for all three.

Mirrors `saena_domain.identity.tenant.TenantContext.require_engine` and
`saena_domain.events.factory._check_engine_id`'s enforcement pattern —
reuses the SAME generated `saena_schemas` enum both of those already consult
(`saena_schemas.envelope.event_envelope_v1.engine_id.Schema`), so there is
only one Python-level closed-enum source across the whole package, never a
duplicated list. This guard is independent of both of those, though: it
needs neither a bound `TenantContext` (identity module) nor an AsyncAPI
channel lookup (events module) — Wave 3 job-kind code that only needs "is
this `engine_id` even permitted at all" calls this directly.
"""

from __future__ import annotations

from saena_schemas.envelope.event_envelope_v1.engine_id import Schema as EngineIdSchema

from saena_domain.execution.errors import EngineDisallowedError, EngineNotPermittedError

ALLOWED_ENGINE_IDS: frozenset[str] = frozenset(item.value for item in EngineIdSchema)

# Explicitly-named v1 rejects (CLAUDE.md "Engine scope (v1)" Disabled list)
# get a distinct, more specific error than an arbitrary unrecognized string
# would — naming exactly which disabled engine family was requested, for a
# clearer audit/log trail.
_KNOWN_DISALLOWED_ENGINE_IDS: dict[str, str] = {
    "google-aio": "Google AI Overviews",
    "google-ai-overviews": "Google AI Overviews",
    "google-ai-mode": "Google AI Mode",
    "gemini": "Gemini",
}


def guard_engine_id(engine_id: str) -> None:
    """Raise unless `engine_id` is the v1 closed enum's sole permitted value.

    Known-disallowed values (google-aio/google-ai-overviews/google-ai-mode/
    gemini) raise the more specific `EngineDisallowedError`; any other
    non-permitted string raises the generic `EngineNotPermittedError`.
    Returns `None` (no exception) when `engine_id` is permitted.
    """
    if engine_id in ALLOWED_ENGINE_IDS:
        return
    disallowed_name = _KNOWN_DISALLOWED_ENGINE_IDS.get(engine_id)
    if disallowed_name is not None:
        raise EngineDisallowedError(engine_id, disallowed_name)
    raise EngineNotPermittedError(engine_id)


__all__ = ["ALLOWED_ENGINE_IDS", "guard_engine_id"]
