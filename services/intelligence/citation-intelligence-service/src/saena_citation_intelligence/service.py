"""`normalize_citation` — orchestrates URL normalization, ownership
classification, and `citation.normalized.v1` event-envelope construction
(w4-05).

This is the ONE public entry point a caller (e.g. a future
intelligence-worker orchestration layer, w4-12) needs: given a raw observed
citation URL plus tenant/run identity and the caller-sourced owned/
competitor domain sets, it returns both the immutable `CitationRecord` and
the ready-to-publish `citation.normalized.v1` envelope (built via
`saena_domain.events.EnvelopeFactory` — never a hand-built dict pretending
to be a valid envelope, same discipline `saena_tenant_control.service`'s
module docstring documents for the same reason).

Deliberately excluded from this module's scope (task brief "FORBIDDEN
(Wave 5/P1)"): no answer-absorption analysis, no contribution/prominence
scoring beyond the ownership classification itself, no outcome/DiD/causal/
lift computation. This module produces a CitationRecord + its normalization
event ONLY — "citation SELECTION intelligence only."
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from saena_domain.events import EnvelopeFactory

from saena_citation_intelligence.errors import EngineNotPermittedError
from saena_citation_intelligence.normalization import normalize_url
from saena_citation_intelligence.ownership import classify_ownership
from saena_citation_intelligence.records import CitationRecord, compute_content_hash

#: v1 closed engine allow-list (CLAUDE.md "Engine scope (v1)"; ADR-0013).
#: This package's OWN guard — fires before `EnvelopeFactory` is even called
#: (see `errors.EngineNotPermittedError` docstring for why this is a
#: separate, earlier check from the factory's own).
ALLOWED_ENGINE_IDS: frozenset[str] = frozenset({"chatgpt-search"})

_PRODUCER = "citation-intelligence-service"
_EVENT_TYPE = "citation.normalized.v1"


def _utc_now_iso() -> str:
    """Render the current UTC instant in the `TimestampUtc` contract shape
    (`^[0-9]{4}-...Z$`, `packages/schemas` common `timestamp_utc` pattern)."""
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class CitationNormalizationResult:
    """`normalize_citation`'s return value: the immutable `CitationRecord`
    plus the `citation.normalized.v1` envelope built for it."""

    record: CitationRecord
    envelope: dict[str, Any]


def normalize_citation(
    *,
    tenant_id: str,
    run_id: str,
    citation_id: str,
    raw_url: str,
    engine_id: str,
    tenant_owned_domains: frozenset[str] = frozenset(),
    competitor_domains: frozenset[str] = frozenset(),
    idempotency_key: str | None = None,
    clock: Callable[[], str] = _utc_now_iso,
) -> CitationNormalizationResult:
    """Normalize `raw_url`, classify its ownership, and build the
    `citation.normalized.v1` envelope for it.

    `engine_id` MUST be `"chatgpt-search"` (CLAUDE.md Engine scope v1) — any
    other value raises `EngineNotPermittedError` immediately, before any URL
    normalization or ownership classification is attempted (fail fast on
    the hardest constraint first).

    `idempotency_key` defaults to `f"{tenant_id}:{run_id}:{citation_id}"`
    (this package's own per-event key rule — `EnvelopeFactory` itself only
    enforces non-empty, per its own docstring "callers own composing the
    key"); a caller may override it explicitly for a different key scheme.

    `clock` is always injectable (default: real UTC now) so this function's
    own unit tests never depend on real wall-clock time — mirrors
    `saena_site_discovery.inventory.run_site_discovery`'s `clock` parameter
    discipline.

    Raises:
        EngineNotPermittedError: `engine_id` is not `"chatgpt-search"`.
        UrlNormalizationError: `raw_url` could not be normalized (empty,
            no scheme/host, disallowed scheme, or unencodable IDN host) —
            or (defense in depth) the constructed `CitationRecord` itself
            fails its own `__post_init__` validation.
        OwnershipClassificationError: `tenant_owned_domains`/
            `competitor_domains` contains a malformed entry.
        saena_domain.events.errors.EnvelopeValidationError: the constructed
            envelope failed dual (jsonschema + pydantic) validation.
    """
    if engine_id not in ALLOWED_ENGINE_IDS:
        raise EngineNotPermittedError(
            f"engine_id {engine_id!r} is not permitted in v1 "
            f"(closed enum: {sorted(ALLOWED_ENGINE_IDS)!r})",
            context={"engine_id": engine_id},
        )

    normalized_uri = normalize_url(raw_url)

    decision = classify_ownership(
        normalized_uri,
        tenant_owned_domains=tenant_owned_domains,
        competitor_domains=competitor_domains,
    )

    content_hash = compute_content_hash(
        citation_id=citation_id,
        normalized_uri=normalized_uri,
        ownership_class=decision.ownership_class,
        ownership_confidence=decision.confidence,
    )

    record = CitationRecord(
        tenant_id=tenant_id,
        citation_id=citation_id,
        normalized_uri=normalized_uri,
        content_hash=content_hash,
        ownership_class=decision.ownership_class,
        ownership_confidence=decision.confidence,
        matched_rule=decision.matched_rule,
        observed_at=clock(),
    )

    resolved_idempotency_key = idempotency_key or f"{tenant_id}:{run_id}:{citation_id}"

    envelope = EnvelopeFactory.build_tenant_envelope(
        producer=_PRODUCER,
        event_type=_EVENT_TYPE,
        tenant_id=tenant_id,
        run_id=run_id,
        idempotency_key=resolved_idempotency_key,
        payload={
            "engine_id": engine_id,
            "citation_id": record.citation_id,
            "normalized_uri": record.normalized_uri,
            "content_hash": record.content_hash,
        },
    )

    return CitationNormalizationResult(record=record, envelope=envelope)


__all__ = [
    "ALLOWED_ENGINE_IDS",
    "CitationNormalizationResult",
    "normalize_citation",
]
