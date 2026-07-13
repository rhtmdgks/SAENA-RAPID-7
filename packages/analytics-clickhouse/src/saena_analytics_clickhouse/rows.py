"""Append-only analytics row models — `observations` / `citations` /
`experiment_registrations` (w4-06 mission deliverables 1 + 3).

Every row is a frozen dataclass carrying ONLY metadata/hash/ref columns —
NEVER raw response/screenshot/source content (data-ownership.md
Constraints: "No PII/secrets in event payloads — object refs + access
policy"; ADR-0007 §Current decision 1 "raw는 object ref만"). Construction
itself is the enforcement point: `__post_init__` on every row class calls
`guard_row_fields` (`guard.py`) against every string field, so a row that
carries an obviously-raw field can never be built in the first place — it
never reaches `query.py`'s INSERT builder or any `ClickHouseExecutor`.

r4-04 (query privacy boundary — SUPERSEDES the pre-fix field below):
`ObservationRow` no longer carries `query_text: str` (the raw customer
query, verbatim, up to 2000 chars — a genuine `data-ownership.md`
Constraints violation: `guard.py`'s SHAPE-only heuristic never caught an
ordinary natural-language query carrying an email/phone/customer name,
since it has no oversize/secret-pattern/forbidden-name shape). It carries
`query_ref: str` (a `query_privacy.QueryRef.query_ref` — opaque,
content-addressed, same "gateway ref, never raw content" discipline as
`raw_object_ref`) and an OPTIONAL `query_digest: str | None` (a
`query_privacy.QueryDigest.digest` — KEYED HMAC-SHA256, only ever present
if a caller actually derived one via `query_privacy.derive_query_digest`
for a genuine correlation need; `None` is the default and the common case).
See `query_privacy.py`'s module docstring for the full mechanism and why an
UNKEYED hash is never an acceptable substitute for `query_digest`. The raw
query itself never reaches this row type, ever, in any field — a caller
that still holds the raw query string must derive a `QueryRef`/`QueryDigest`
BEFORE constructing this row; there is no code path here that accepts raw
query text.

`ObservationRow`'s field set otherwise mirrors
`saena_chatgpt_observer.observation.PlatformObservation` (`engine_id`,
`tenant_id`, `run_id`, `citation_refs`, `raw_object_ref` — that service's
own `query_text: str` field is UNCHANGED by this fix: `PlatformObservation`
may still hold the raw query in-memory, transiently, upstream of this
package's persistence boundary, per r4-04 task instruction point 2; it is
simply never projected into this row verbatim any more) —
that service is PlatformObservation's first, engine-neutral implementation
(ADR-0007 §1) and this package's `observations` table is its ClickHouse
analytical projection; reusing the same field names/shapes (`query_ref`
excepted, a NEW field this package's own persistence boundary introduces)
keeps a future `ChatgptObserverService -> analytics-clickhouse` writer a
straight field copy for every OTHER field, not a translation layer.
`ObservationRow` does NOT import `PlatformObservation` itself (this package
is a standalone leaf, see `pyproject.toml`) — the shapes are independently
defined and kept in sync by convention + this docstring, not by a shared
base class.

Every row carries a non-optional `tenant_id` (discriminator, ADR-0007
rev.2/ADR-0014 — no exemption: none of these three tables is
`SystemContext`-scoped global metadata) and a non-optional
`idempotency_key`, the dedup key `ClickHouseAnalyticsStore.append_*`
(`store.py`) checks before every INSERT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from saena_analytics_clickhouse.errors import RowValidationError
from saena_analytics_clickhouse.guard import guard_row_fields
from saena_analytics_clickhouse.identifiers import (
    validate_nonempty_str,
    validate_tenant_id,
    validate_utc_datetime,
)

_OPAQUE_REF_MAX_LENGTH = 512  # matches PlatformObservation's own cap
_HASH_MAX_LENGTH = 256
_QUERY_DIGEST_MAX_LENGTH = 256  # "hmac-sha256:" prefix + 64 hex chars


@dataclass(frozen=True, slots=True)
class ObservationRow:
    """One `observations` table row — a ChatGPT Search ROL capture, engine
    neutral (`engine_id` required, ADR-0007 §1).

    r4-04: `query_ref` (required) + `query_digest` (optional) REPLACE the
    pre-fix `query_text: str` field — see module docstring "r4-04" section
    and `query_privacy.py`. Neither field ever carries the raw query;
    `query_ref` is an opaque `query_privacy.derive_query_ref(...).query_ref`
    string, `query_digest` (when present) is a
    `query_privacy.derive_query_digest(...).digest` KEYED HMAC string.
    """

    tenant_id: str
    id: str
    idempotency_key: str
    occurred_at: datetime
    engine_id: str
    run_id: str
    query_ref: str
    citation_refs: tuple[str, ...]
    raw_object_ref: str
    query_digest: str | None = field(default=None)
    ingested_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        validate_tenant_id(self.tenant_id)
        validate_nonempty_str(self.id, field_name="id")
        validate_nonempty_str(self.idempotency_key, field_name="idempotency_key")
        validate_utc_datetime(self.occurred_at, field_name="occurred_at")
        if self.ingested_at is not None:
            validate_utc_datetime(self.ingested_at, field_name="ingested_at")
        validate_nonempty_str(self.engine_id, field_name="engine_id")
        validate_nonempty_str(self.run_id, field_name="run_id")
        validate_nonempty_str(
            self.query_ref, field_name="query_ref", max_length=_OPAQUE_REF_MAX_LENGTH
        )
        if self.query_digest is not None:
            validate_nonempty_str(
                self.query_digest,
                field_name="query_digest",
                max_length=_QUERY_DIGEST_MAX_LENGTH,
            )
        validate_nonempty_str(
            self.raw_object_ref, field_name="raw_object_ref", max_length=_OPAQUE_REF_MAX_LENGTH
        )
        for ref in self.citation_refs:
            validate_nonempty_str(
                ref, field_name="citation_refs[]", max_length=_OPAQUE_REF_MAX_LENGTH
            )
        guard_row_fields(
            {
                "tenant_id": self.tenant_id,
                "id": self.id,
                "idempotency_key": self.idempotency_key,
                "engine_id": self.engine_id,
                "run_id": self.run_id,
                "query_ref": self.query_ref,
                "query_digest": self.query_digest,
                "raw_object_ref": self.raw_object_ref,
                **{f"citation_refs[{i}]": ref for i, ref in enumerate(self.citation_refs)},
            }
        )


@dataclass(frozen=True, slots=True)
class CitationRow:
    """One `citations` table row — citation-intelligence-service's
    `citation.normalized.v1` projection (contract-catalog.md: "Published
    events | citation.normalized.v1"; owner = citation-intelligence-service,
    `docs/architecture/data-ownership.md`).

    `citation_ref` reuses the same opaque-reference discipline as
    `ObservationRow.citation_refs[]` (never a raw citation snippet/URL with
    a query string, see `PlatformObservation`'s own docstring)."""

    tenant_id: str
    id: str
    idempotency_key: str
    occurred_at: datetime
    run_id: str
    observation_id: str
    citation_ref: str
    source_domain: str
    contribution_score: float
    ingested_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        validate_tenant_id(self.tenant_id)
        validate_nonempty_str(self.id, field_name="id")
        validate_nonempty_str(self.idempotency_key, field_name="idempotency_key")
        validate_utc_datetime(self.occurred_at, field_name="occurred_at")
        if self.ingested_at is not None:
            validate_utc_datetime(self.ingested_at, field_name="ingested_at")
        validate_nonempty_str(self.run_id, field_name="run_id")
        validate_nonempty_str(self.observation_id, field_name="observation_id")
        validate_nonempty_str(
            self.citation_ref, field_name="citation_ref", max_length=_OPAQUE_REF_MAX_LENGTH
        )
        validate_nonempty_str(self.source_domain, field_name="source_domain", max_length=255)
        if not (0.0 <= self.contribution_score <= 1.0):
            raise RowValidationError(
                "contribution_score must be within [0.0, 1.0]",
                context={"field": "contribution_score", "value": self.contribution_score},
            )
        guard_row_fields(
            {
                "tenant_id": self.tenant_id,
                "id": self.id,
                "idempotency_key": self.idempotency_key,
                "run_id": self.run_id,
                "observation_id": self.observation_id,
                "citation_ref": self.citation_ref,
                "source_domain": self.source_domain,
            }
        )


@dataclass(frozen=True, slots=True)
class ExperimentRegistrationRow:
    """One `experiment_registrations` table row — QueryExperiment
    pre-registration metadata (contract-catalog.md: "QueryExperiment |
    experiment-attribution | 사전등록 후 immutable — 등록 hash를
    audit-ledger 앵커링 (H-3)").

    `registration_hash` is the H-3 content hash anchored to the audit
    ledger at registration time — this table stores the SAME hash as a
    cross-reference (never the registration payload itself beyond the
    engine-neutral, non-sensitive scheduling metadata below: `engine_id`,
    `locale`, `observation_cell`, `status`)."""

    tenant_id: str
    id: str
    idempotency_key: str
    occurred_at: datetime
    engine_id: str
    locale: str
    observation_cell: str
    registration_hash: str
    status: str
    ingested_at: datetime | None = field(default=None)

    _ALLOWED_STATUSES = ("registered", "amended", "completed", "cancelled")

    def __post_init__(self) -> None:
        validate_tenant_id(self.tenant_id)
        validate_nonempty_str(self.id, field_name="id")
        validate_nonempty_str(self.idempotency_key, field_name="idempotency_key")
        validate_utc_datetime(self.occurred_at, field_name="occurred_at")
        if self.ingested_at is not None:
            validate_utc_datetime(self.ingested_at, field_name="ingested_at")
        validate_nonempty_str(self.engine_id, field_name="engine_id")
        validate_nonempty_str(self.locale, field_name="locale", max_length=32)
        validate_nonempty_str(self.observation_cell, field_name="observation_cell", max_length=255)
        validate_nonempty_str(
            self.registration_hash, field_name="registration_hash", max_length=_HASH_MAX_LENGTH
        )
        if self.status not in self._ALLOWED_STATUSES:
            raise RowValidationError(
                f"status {self.status!r} not in {self._ALLOWED_STATUSES}",
                context={"field": "status", "value": self.status},
            )
        guard_row_fields(
            {
                "tenant_id": self.tenant_id,
                "id": self.id,
                "idempotency_key": self.idempotency_key,
                "engine_id": self.engine_id,
                "locale": self.locale,
                "observation_cell": self.observation_cell,
                "registration_hash": self.registration_hash,
                "status": self.status,
            }
        )


__all__ = ["CitationRow", "ExperimentRegistrationRow", "ObservationRow"]
