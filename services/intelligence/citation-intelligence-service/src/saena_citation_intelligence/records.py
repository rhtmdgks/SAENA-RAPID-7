"""`CitationRecord` — immutable, tenant-scoped normalized-citation value
object (w4-05).

Mirrors `saena_site_discovery.records.ContentRecordProjection`'s frozen/
validated-`__post_init__` discipline. This is this SERVICE's own
domain-internal record — the task brief's fallback instruction (see
`citation-normalized.schema.json`'s own `$comment`: "no citation-record
domain contract exists in this catalog ... this payload stays
self-contained") means there is no `packages/contracts` "CitationRecord"
schema to bind to; `content_hash` is instead this record's sole ledger
anchor, computed over a canonical JSON projection of this record via
`saena_domain.audit.canonical` (no new hashing rule invented, per the task
brief).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from saena_domain.audit import canonical_json, sha256_hex

from saena_citation_intelligence.errors import UrlNormalizationError
from saena_citation_intelligence.ownership import OwnershipClass

_CITATION_ID_MAX_LENGTH = 128
_URI_REF_PATTERN = re.compile(r"^[a-z0-9+.-]+://[^?#]+$")
_TENANT_ID_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$")


def compute_content_hash(
    *,
    citation_id: str,
    normalized_uri: str,
    ownership_class: OwnershipClass,
    ownership_confidence: float,
) -> str:
    """Return the `sha256:<hex>` content hash anchoring this citation
    record (`sha256_ref` contract pattern,
    `packages/contracts/json-schema/common/identifiers/v1/
    identifiers.schema.json`).

    Uses `saena_domain.audit.canonical.canonical_json` (sorted-keys, compact,
    ASCII-safe) + `sha256_hex` — the SAME canonicalization the audit hash
    chain uses (task brief: "do NOT invent a new hashing rule"). Two calls
    with the same 4 keyword arguments always produce the same hash
    (determinism contract), regardless of caller-side dict key ordering.
    """
    projection = {
        "citation_id": citation_id,
        "normalized_uri": normalized_uri,
        "ownership_class": ownership_class.value,
        "ownership_confidence": ownership_confidence,
    }
    return f"sha256:{sha256_hex(canonical_json(projection))}"


@dataclass(frozen=True, slots=True)
class CitationRecord:
    """Immutable, tenant-scoped normalized-citation record.

    `normalized_uri` is ALWAYS the `normalize_url`-produced canonical form
    (never a raw/unnormalized URL) and `content_hash` is ALWAYS the
    `compute_content_hash` output for this record's own fields — both are
    re-validated at construction time (defense in depth, matching
    `ContentRecordProjection`'s own discipline), not merely trusted from the
    caller.
    """

    tenant_id: str
    citation_id: str
    normalized_uri: str
    content_hash: str
    ownership_class: OwnershipClass
    ownership_confidence: float
    matched_rule: str
    observed_at: str

    def __post_init__(self) -> None:
        if not _TENANT_ID_PATTERN.match(self.tenant_id):
            raise UrlNormalizationError(
                f"tenant_id {self.tenant_id!r} does not match the ADR-0014 tenant_id pattern",
                context={"field": "tenant_id"},
            )
        if not self.citation_id or len(self.citation_id) > _CITATION_ID_MAX_LENGTH:
            raise UrlNormalizationError(
                f"citation_id must be 1-{_CITATION_ID_MAX_LENGTH} chars",
                context={"field": "citation_id", "citation_id": self.citation_id},
            )
        if not _URI_REF_PATTERN.match(self.normalized_uri):
            raise UrlNormalizationError(
                f"normalized_uri {self.normalized_uri!r} is not a well-formed uri_ref "
                "(scheme required, '?'/'#' forbidden)",
                context={"field": "normalized_uri"},
            )
        expected_hash = compute_content_hash(
            citation_id=self.citation_id,
            normalized_uri=self.normalized_uri,
            ownership_class=self.ownership_class,
            ownership_confidence=self.ownership_confidence,
        )
        if self.content_hash != expected_hash:
            raise UrlNormalizationError(
                "content_hash does not match the canonical hash of this record's own "
                "fields (never caller-trusted)",
                context={"field": "content_hash"},
            )
        if not (0.0 <= self.ownership_confidence <= 1.0):
            raise UrlNormalizationError(
                f"ownership_confidence {self.ownership_confidence!r} must be in [0.0, 1.0]",
                context={"field": "ownership_confidence"},
            )
        if not self.observed_at:
            raise UrlNormalizationError(
                "observed_at must be a non-empty string", context={"field": "observed_at"}
            )


__all__ = ["CitationRecord", "compute_content_hash"]
